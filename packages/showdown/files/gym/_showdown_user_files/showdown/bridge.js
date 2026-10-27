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
//   {cmd:"ping"} / {cmd:"quit"}
const readline = require('readline');
const G = require('./gymsim.js');
const {newBattle, mc, usableMoves, settleSwitches, strongest, randomChoice, planChoice, view} = G;
// ------------------------------------------------------------------- I/O --
let b = null, sent = 0;
const reply = o => process.stdout.write(JSON.stringify(o) + '\n');
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
      b = newBattle(cmd.p1, cmd.p2);
      G.hpScale(b, cmd.hpmult || 1);             // battle HP (Ankimon divides it back)
      G.dmaxReady(b);
      G.teraReady(b);
      G.totemStart(b, cmd.totem || null);
      G.titanStart(b, cmd.titan || null);
      G.guardStart(b, cmd.guard || null);
      const v = view(b, 0); sent = b.log.length; return reply(v);
    }
    if (!b) return reply({ok: false, error: 'no battle'});
    if (cmd.cmd === 'turn') {
      if (b.ended) return reply(view(b, sent));
      let c1;
      const opts = usableMoves(b.p1);
      const zs = G.zOptions(b);
      if (cmd.move) {
        const o = opts.find(m => m.id === cmd.move);
        c1 = o ? 'move ' + o.i : (opts.length ? 'move ' + opts[0].i : 'default');
        if (o && cmd.z === true && zs && zs[o.i - 1]) c1 += ' zmove';
        else if (o && cmd.dmax === true && G.canDmax(b.p1)) c1 += ' dynamax';
        else if (o && cmd.tera === true && G.canTera(b.p1)) c1 += ' terastallize';
      }
      else c1 = (cmd.z === 'auto' && G.autoZ(b)) || (cmd.dmax === 'auto' && G.autoDmax(b))
        || (cmd.tera === 'auto' && G.autoTera(b)) || strongest(b.p1, b.p2);
      const c2 = G.totemChoice(b) || G.teraLeader(b, G.dmaxLeader(b, cmd.smart === false ? randomChoice(b.p2) : planChoice(b)));
      // Tera: the move picked becomes Tera Blast first, so Tera Blast is what's used (PP 10 -> 9)
      const tm = /^move (\d+) terastallize$/.exec(c1 || '');
      if (tm) G.teraBlastAt(b, b.p1, +tm[1] - 1);
      mc(b, c1, c2);
      G.teraBlastSwap(b);
      if (G.ctx.titan) G.titanSettle(b);
      if (G.ctx.totem) G.totemSettle(b); else settleSwitches(b);
      const v = view(b, sent); sent = b.log.length; return reply(v);
    }
    reply({ok: false, error: 'unknown cmd ' + cmd.cmd});
  } catch (e) { reply({ok: false, error: String((e && e.stack) || e).slice(0, 800)}); }
});
process.stdin.on('end', () => process.exit(0));   // Anki closed the pipe: exit
