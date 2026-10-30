'use strict';
// Ankimon gym helper: runs one gym fight on Pokemon Showdown's simulator
// (@pkmn/sim) via gymsim.js. One JSON command per line on stdin, one JSON reply
// per line. Nothing here touches the network.
//   {cmd:"start", p1:[sets], p2:[sets], leader:"Erika", wild:false}
//      sets may carry curhp / status / pp (expeditions: damage carries over)
//      totem:{aura:{def:1}} = an Alola totem trial (p2 = totem + reinforcements)
//   {cmd:"turn", move:"flamewheel"|null, smart:true|false}   move null = auto
//      z:true = use that move as a Z-Move; z:"auto" = auto-battle may spend it
//      dmax:true = Dynamax with that move; dmax:"auto" = auto-battle may Dynamax
//   start may carry dynamax:{p1:bool, p2:bool} (Galar: who may Dynamax)
//      tera:true = Terastallize with that move; tera:"auto" = auto-battle may
//   start may carry tera:{p1:bool, p2:bool} (Paldea: who may Terastallize)
//      titan:{aura:{...}, power:{...}} = a Paldea Titan (p2 = the Titan alone)
//   start may carry aiswitch:{max:3, gap:5} (Elite Four, Champions, rematches:
//      the leader may switch, that often, that far apart - gymsim.aiSwitch)
//   turn may carry switchto:k = switch to your team slot k instead of a move
//      (uses the turn; ignored if it can't happen - a move is used instead)
//   {cmd:"rate", lineups:[[sets]...], p2:[sets], fights:4, hpmult:2} -> {results:[{wins, left}]}
//      quick fights per lineup for "Choose team for me" (gym/autopick.py)
//   {cmd:"ping"} / {cmd:"quit"}
const readline = require('readline');
const G = require('./gymsim.js');
const {newBattle, mc, usableMoves, settleSwitches, strongest, randomChoice, planChoice, view} = G;
// ------------------------------------------------------------------- I/O --
let b = null, sent = 0;
const reply = o => process.stdout.write(JSON.stringify(o) + '\n');
// Two of one species on a side (Jasmine's Magnemite, Lance's Dragonite): the second is
// "Magnemite (2)" in the log, so a faint replacement doesn't read like the first one again.
const labelTwins = team => {
  const seen = {};
  return (team || []).map(s => {
    const k = s.name || s.species || '';
    seen[k] = (seen[k] || 0) + 1;
    return seen[k] > 1 ? Object.assign({}, s, {name: k.slice(0, 13) + ' (' + seen[k] + ')'}) : s;
  });
};
// Showdown's log only shows a switch-in; a switch by choice also says who came back.
function withdrawLines(log, back) {
  const at = (pre, text) => {
    const i = (log || []).findIndex(l => l.startsWith(pre));
    if (i >= 0) log.splice(i, 0, text);
  };
  if (back[1]) at(G.ctx.leader + ' sent out ', G.ctx.leader + ' withdrew ' + back[1] + '!');
  if (back[0]) at('Go! ', 'Come back, ' + back[0] + '!');
}
readline.createInterface({input: process.stdin}).on('line', line => {
  let cmd;
  try { cmd = JSON.parse(line); } catch (e) { return reply({ok: false, error: 'bad json'}); }
  try {
    if (cmd.cmd === 'ping') return reply({ok: true, sim: 'showdown'});
    if (cmd.cmd === 'quit') { reply({ok: true}); process.exit(0); }
    if (cmd.cmd === 'start') {
      G.ctx.leader = cmd.leader || 'The leader';
      G.ctx.wild = !!cmd.wild;
      G.dmaxStart(cmd.dynamax || null);          // before newBattle: the first request offers it
      G.teraStart(cmd.tera || null);
      b = newBattle(labelTwins(cmd.p1), labelTwins(cmd.p2));
      G.hpScale(b, cmd.hpmult || 1);             // battle HP (Ankimon divides it back)
      G.dmaxReady(b);
      G.teraReady(b);
      G.totemStart(b, cmd.totem || null);
      G.titanStart(b, cmd.titan || null);
      G.guardStart(b, cmd.guard || null);
      G.aiSwitchStart(cmd.aiswitch || null);
      const v = view(b, 0); sent = b.log.length; return reply(v);
    }
    if (cmd.cmd === 'rate') {
      // "Choose team for me" (gym/autopick.py): a few quick fights per lineup
      // against p2 - you attack with your strongest move, the leader plans
      // (lighter than in a real fight). Its own battles: a live fight is untouched.
      const fights = cmd.fights || 3, out = [];
      G.dmaxStart(null);
      G.teraStart(null);
      G.aiSwitchStart(null);
      for (const team of cmd.lineups || []) {
        let wins = 0, left = 0;
        for (let f = 0; f < fights; f++) {
          const r = newBattle(team, cmd.p2);
          G.hpScale(r, cmd.hpmult || 1);
          let t = 0;
          while (!r.ended && t++ < (cmd.maxturns || 150)) {
            mc(r, strongest(r.p1, r.p2), planChoice(r, 1, 5));
            settleSwitches(r);
          }
          if (r.winner === 'You') wins++;
          left += r.p1.pokemon.reduce((s, p) => s + p.hp / p.maxhp, 0) / r.p1.pokemon.length;
        }
        out.push({wins, left: left / fights});
      }
      return reply({ok: true, results: out});
    }
    if (!b) return reply({ok: false, error: 'no battle'});
    if (cmd.cmd === 'turn') {
      if (b.ended) return reply(view(b, sent));
      let c1 = cmd.switchto != null ? G.switchTo(b.p1, cmd.switchto) : null;
      const opts = usableMoves(b.p1);
      const zs = G.zOptions(b);
      if (c1) { /* your switch: the whole turn */ }
      else if (cmd.move) {
        const o = opts.find(m => m.id === cmd.move);
        c1 = o ? 'move ' + o.i : (opts.length ? 'move ' + opts[0].i : 'default');
        if (o && cmd.z === true && zs && zs[o.i - 1]) c1 += ' zmove';
        else if (o && cmd.dmax === true && G.canDmax(b.p1)) c1 += ' dynamax';
        else if (o && cmd.tera === true && G.canTera(b.p1)) c1 += ' terastallize';
      }
      else c1 = (cmd.z === 'auto' && G.autoZ(b)) || (cmd.dmax === 'auto' && G.autoDmax(b))
        || (cmd.tera === 'auto' && G.autoTera(b)) || strongest(b.p1, b.p2);
      const c2 = G.totemChoice(b) || (cmd.smart !== false && G.aiSwitch(b))
        || G.teraLeader(b, G.dmaxLeader(b, cmd.smart === false ? randomChoice(b.p2) : planChoice(b)));
      c1 = G.megaChoice(b, b.p1, c1);          // daily Megas: today's Mega Evolves with its first move
      const c2m = G.megaChoice(b, b.p2, c2);    // and a rematched leader's
      const mark = b.log.length;
      // Tera: the move picked becomes Tera Blast first, so Tera Blast is what's used (PP 10 -> 9)
      const tm = /^move (\d+) terastallize$/.exec(c1 || '');
      if (tm) G.teraBlastAt(b, b.p1, +tm[1] - 1);
      const back = [[c1, b.p1], [c2m, b.p2]].map(([c, side]) =>
        /^switch /.test(c || '') && G.active(side) ? G.active(side).name : null);
      mc(b, c1, c2m);
      G.aiSwitchNote(c2m, b.log.slice(mark));
      G.teraBlastSwap(b);
      if (G.ctx.titan) G.titanSettle(b);
      if (G.ctx.totem) G.totemSettle(b); else settleSwitches(b);
      const v = view(b, sent); sent = b.log.length;
      withdrawLines(v.log, back);
      return reply(v);
    }
    reply({ok: false, error: 'unknown cmd ' + cmd.cmd});
  } catch (e) { reply({ok: false, error: String((e && e.stack) || e).slice(0, 800)}); }
});
process.stdin.on('end', () => process.exit(0));   // Anki closed the pipe: exit
