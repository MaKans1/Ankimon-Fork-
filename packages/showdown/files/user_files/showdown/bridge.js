'use strict';
// Ankimon gym helper: runs one gym fight on Pokemon Showdown's simulator
// (@pkmn/sim) via gymsim.js. One JSON command per line on stdin, one JSON reply
// per line. Nothing here touches the network.
//   {cmd:"start", p1:[sets], p2:[sets], leader:"Erika", wild:false}
//      sets may carry curhp / status / pp (expeditions: damage carries over)
//   {cmd:"turn", move:"flamewheel"|null, smart:true|false}   move null = auto
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
      b = newBattle(cmd.p1, cmd.p2);
      const v = view(b, 0); sent = b.log.length; return reply(v);
    }
    if (!b) return reply({ok: false, error: 'no battle'});
    if (cmd.cmd === 'turn') {
      if (b.ended) return reply(view(b, sent));
      let c1;
      const opts = usableMoves(b.p1);
      if (cmd.move) { const o = opts.find(m => m.id === cmd.move); c1 = o ? 'move ' + o.i : (opts.length ? 'move ' + opts[0].i : 'default'); }
      else c1 = strongest(b.p1, b.p2);
      const c2 = cmd.smart === false ? randomChoice(b.p2) : planChoice(b);
      mc(b, c1, c2);
      settleSwitches(b);
      const v = view(b, sent); sent = b.log.length; return reply(v);
    }
    reply({ok: false, error: 'unknown cmd ' + cmd.cmd});
  } catch (e) { reply({ok: false, error: String((e && e.stack) || e).slice(0, 800)}); }
});
process.stdin.on('end', () => process.exit(0));   // Anki closed the pipe: exit
