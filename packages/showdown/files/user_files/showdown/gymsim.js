'use strict';
// gymsim.js - Ankimon gym battle library (Pokemon Showdown). Used by bridge.js (live gyms)
// and tune.js (boss tuning), so both run identical code.
// Ankimon gym helper: runs one gym fight on Pokemon Showdown's simulator
// (@pkmn/sim). One JSON command per line on stdin, one JSON reply per line.
//   {cmd:"start", p1:[sets], p2:[sets], leader:"Erika"}
//   {cmd:"turn", move:"flamewheel"|null, smart:true|false}   move null = auto
//   {cmd:"ping"} / {cmd:"quit"}
// Gym rules: base PP (no PP Ups), no voluntary switching, a fainted Pokemon is
// replaced by the next one in team order. Nothing here touches the network.
const {Battle, Dex, Teams, PRNG} = require('@pkmn/sim');
const readline = require('readline');
const dex = Dex.forGen(9);

// ------------------------------------------------------------- team sets --
const clamp = (v, lo, hi, d) => { v = Number(v); return Number.isFinite(v) ? Math.max(lo, Math.min(hi, Math.round(v))) : d; };
function cleanSet(s) {
  const sp = dex.species.get(s.species || s.name || '');
  if (!sp.exists) throw new Error('unknown species: ' + (s.species || s.name));
  const stat = (o, lo, hi, d) => { const r = {}; for (const k of ['hp', 'atk', 'def', 'spa', 'spd', 'spe']) r[k] = clamp((o || {})[k], lo, hi, d); return r; };
  let moves = (s.moves || []).map(m => dex.moves.get(m)).filter(m => m.exists).map(m => m.id).slice(0, 4);
  if (!moves.length) moves = ['struggle'];
  const ab = dex.abilities.get(s.ability || '');
  const item = dex.items.get(s.item || '');
  const nat = dex.natures.get(s.nature || 'Serious');
  let gender = sp.gender || (s.gender === 'M' || s.gender === 'F' ? s.gender : '');
  return {name: (s.name || sp.name).slice(0, 18), species: sp.name, level: clamp(s.level, 1, 100, 50),
    ability: ab.exists ? ab.name : sp.abilities['0'], item: item.exists ? item.name : '',
    nature: nat.exists ? nat.name : 'Serious', gender, shiny: !!s.shiny,
    ivs: stat(s.ivs, 0, 31, 15), evs: stat(s.evs, 0, 252, 0), moves};
}

// ---------------------------------------------------------------- battle --
function newBattle(t1, t2) {
  const b = new Battle({formatid: 'gen9customgame', seed: PRNG.generateSeed()});
  b.setPlayer('p1', {name: 'You', team: Teams.pack(t1.map(cleanSet))});
  b.setPlayer('p2', {name: 'Leader', team: Teams.pack(t2.map(cleanSet))});
  if (b.p1.requestState === 'teampreview') mc(b, 'default', 'default');
  for (const side of b.sides) side.pokemon.forEach((p, i) => {
    p.ankimonIndex = i;                                   // original team slot
    for (const ms of [...p.moveSlots, ...p.baseMoveSlots]) {
      const mv = dex.moves.get(ms.id);
      if (mv.exists && mv.pp) ms.pp = ms.maxpp = mv.pp;   // base PP, no PP Ups
    }
  });
  carryOver(b, [t1, t2]);
  return b;
}
// Expeditions: a team can start a fight already worn down - HP, status and PP
// carried over from the last floor (set fields curhp / status / pp). Gym sets
// don't have them, so gyms start fresh exactly as before.
function carryOver(b, teams) {
  let changed = false;
  b.sides.forEach((side, si) => side.pokemon.forEach((p, i) => {
    const s = (teams[si] || [])[i] || {};
    if (s.pp) for (const ms of p.moveSlots) if (s.pp[ms.id] != null) { ms.pp = clamp(s.pp[ms.id], 0, ms.maxpp, ms.pp); changed = true; }
    if (s.curhp != null && s.curhp < p.maxhp) { p.sethp(clamp(s.curhp, 1, p.maxhp, p.maxhp)); changed = true; }
    if (s.status) { const mark = b.log.length; p.setStatus(s.status, p, null, true); b.log.length = mark; changed = true; }
  }));
  // The opening move request was built before this ran; rebuild it so a move
  // carried in at 0 PP isn't offered ("Not all choices done" otherwise).
  if (changed && !b.ended) b.makeRequest();
}
// Driven directly, a battle never "sends" its log; Showdown's loop guard trips
// after 1000 unsent lines. Mark it sent after every turn.
function mc(b, c1, c2) { b.makeChoices(c1, c2); b.sentLogPos = b.log.length; }
const active = side => side.active[0];
function usableMoves(side) {
  const req = side.activeRequest;
  if (!req || !req.active) return [];
  return req.active[0].moves.map((m, i) => ({i: i + 1, id: m.id, disabled: m.disabled})).filter(m => !m.disabled);
}
function nextSwitch(side) {
  const cands = side.pokemon.map((p, idx) => ({p, idx})).filter(x => !x.p.fainted && !x.p.isActive);
  if (!cands.length) return 'pass';
  cands.sort((a, b) => (a.p.ankimonIndex ?? a.idx) - (b.p.ankimonIndex ?? b.idx));
  return 'switch ' + (cands[0].idx + 1);
}
function settleSwitches(b) {
  let guard = 0;
  while (!b.ended && guard++ < 8 && (b.p1.requestState === 'switch' || b.p2.requestState === 'switch'))
    mc(b, b.p1.requestState === 'switch' ? nextSwitch(b.p1) : 'pass', b.p2.requestState === 'switch' ? nextSwitch(b.p2) : 'pass');
}

// ------------------------------------------------------------ move choice --
function estDamage(att, def, moveId) {
  const m = dex.moves.get(moveId);
  if (!att || !def || m.category === 'Status') return 0;
  if (m.ohko) return 0.3 * def.hp;
  const bp = m.basePower || (m.damage === 'level' ? att.level : 0);
  if (!bp) return 0;
  // unmodified = true: stat stages count, but no ability/item Modify events.
  // Those handlers expect a real move (Torrent, Blaze, Overgrow, Swarm read
  // move.type) and threw "Cannot read properties of null" on an estimate.
  const A = att.getStat(m.category === 'Physical' ? 'atk' : 'spa', false, true);
  const D = Math.max(1, def.getStat(m.category === 'Physical' ? 'def' : 'spd', false, true));
  const stab = att.hasType(m.type) ? 1.5 : 1;
  const eff = def.runImmunity(m.type) ? Math.pow(2, dex.getEffectiveness(m.type, def)) : 0;
  const acc = m.accuracy === true ? 1 : m.accuracy / 100;
  return (((2 * att.level / 5 + 2) * bp * A / D) / 50 + 2) * stab * eff * acc;
}
function strongest(side, foe) {
  const opts = usableMoves(side);
  if (!opts.length) return 'default';
  let best = opts[0], bv = -1;
  for (const o of opts) { const v = estDamage(active(side), active(foe), o.id); if (v > bv) { bv = v; best = o; } }
  return 'move ' + best.i;
}
function randomChoice(side) {
  const opts = usableMoves(side);
  return opts.length ? 'move ' + opts[Math.floor(Math.random() * opts.length)].i : 'default';
}
function score(b) {    // from the leader's view: lower is better for the leader
  const hp = s => s.pokemon.reduce((a, p) => a + (p.fainted ? 0 : p.hp / p.maxhp), 0);
  const edge = s => { const a = active(s); if (!a) return 0;
    return Object.values(a.boosts).reduce((x, y) => x + y, 0) * 0.1 - (a.status ? 0.25 : 0); };
  return (hp(b.p1) + edge(b.p1)) - (hp(b.p2) + edge(b.p2));
}
// Planning leader: play each move a few turns forward on forked battles
// (both sides then press their strongest attack) and keep the move that
// leaves the player worst off. Reads the live battle every turn - no script.
function planChoice(b, rollouts = 3, horizon = 8) {
  const opts = usableMoves(b.p2);
  if (opts.length <= 1) return opts.length ? 'move ' + opts[0].i : 'default';
  const snap = b.toJSON();
  let best = opts[0], bv = Infinity;
  for (const o of opts) {
    let tot = 0;
    for (let r = 0; r < rollouts; r++) {
      const c = Battle.fromJSON(snap);
      c.log = c.log.slice();           // fromJSON shares the log array with the original
      c.resetRNG(PRNG.generateSeed());
      c.sentLogPos = c.log.length;
      try {
        mc(c, strongest(c.p1, c.p2), 'move ' + o.i);
        for (let t = 1; t < horizon && !c.ended; t++) {
          if (c.p1.requestState === 'switch' || c.p2.requestState === 'switch') break;
          mc(c, strongest(c.p1, c.p2), strongest(c.p2, c.p1));
        }
      } catch (e) { /* a rollout that errors just scores where it stopped */ }
      tot += score(c);
    }
    if (tot < bv) { bv = tot; best = o; }
  }
  return 'move ' + best.i;
}

// ------------------------------------------------------- readable log text --
const ctx = {leader: 'The leader', wild: false};
const STATUS = {par: 'is paralyzed! It may be unable to move!', brn: 'was burned!', psn: 'was poisoned!',
  tox: 'was badly poisoned!', slp: 'fell asleep!', frz: 'was frozen solid!'};
const CANT = {par: 'is paralyzed! It can\'t move!', slp: 'is fast asleep.', frz: 'is frozen solid!',
  flinch: 'flinched and couldn\'t move!', recharge: 'must recharge!', Truant: 'is loafing around!',
  nopp: 'has no moves left!'};
// partial-trapping moves (Wrap, Bind, Fire Spin...): the start line Showdown sends is an -activate
const TRAP = {
  'Wrap': (t, s) => `${t} was wrapped by ${s}!`,
  'Bind': (t, s) => `${t} was squeezed by ${s}!`,
  'Fire Spin': t => `${t} became trapped in the fiery vortex!`,
  'Whirlpool': t => `${t} became trapped in the vortex!`,
  'Sand Tomb': t => `${t} became trapped by the quicksand!`,
  'Clamp': (t, s) => `${cap(s)} clamped down on ${t.replace(/^[A-Z]/, c => c.toLowerCase())}!`,
  'Infestation': (t, s) => `${t} has been afflicted with an infestation by ${s}!`,
  'Magma Storm': t => `${t} became trapped by swirling magma!`,
  'Snap Trap': t => `${t} got trapped by a snap trap!`,
  'Thunder Cage': (t, s) => `${cap(s)} trapped ${t.replace(/^[A-Z]/, c => c.toLowerCase())}!`,
};
const STAT = {atk: 'Attack', def: 'Defense', spa: 'Sp. Atk', spd: 'Sp. Def', spe: 'Speed', accuracy: 'accuracy', evasion: 'evasiveness'};
function who(ident) {                     // "p1a: Growlithe" -> "your Growlithe"
  const m = /^(p[12])[a-z]?: (.*)$/.exec(ident || '');
  if (!m) return ident || '';
  return (m[1] === 'p1' ? 'your ' : 'the foe\'s ') + m[2];
}
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : s;
const clean = e => (e || '').replace(/^(move|ability|item): /, '');
function fromOf(parts) { const f = parts.find(p => p.startsWith('[from]')); return f ? clean(f.slice(7).trim()) : ''; }
function fmt(line) {
  const p = line.split('|').slice(1), t = p[0];
  const from = fromOf(p);
  switch (t) {
    case 'move': return `${cap(who(p[1]))} used ${p[2]}!` + (p.includes('[miss]') ? '' : '');
    case 'switch': return p[1].startsWith('p1') ? `Go! ${p[1].split(': ')[1]}!`
      : ctx.wild ? `A wild ${p[1].split(': ')[1]} appeared!` : `${ctx.leader} sent out ${p[1].split(': ')[1]}!`;
    case 'drag': return `${cap(who(p[1]))} was dragged out!`;
    case 'faint': return `${cap(who(p[1]))} fainted!`;
    case '-supereffective': return 'It\'s super effective!';
    case '-resisted': return 'It\'s not very effective...';
    case '-immune': return from ? `${cap(who(p[1]))}'s ${from} made the attack useless!` : `It doesn't affect ${who(p[1])}...`;
    case '-crit': return 'A critical hit!';
    case '-miss': return `${cap(who(p[1]))}'s attack missed!`;
    case '-fail': return 'But it failed!';
    case '-ohko': return 'It\'s a one-hit KO!';
    case '-hitcount': return `Hit ${p[2]} time(s)!`;
    case '-status': return `${cap(who(p[1]))} ${STATUS[p[2]] || 'got ' + p[2]}` + (from ? ` (${from})` : '');
    case '-curestatus': return p[2] === 'slp' ? `${cap(who(p[1]))} woke up!` : p[2] === 'frz' ? `${cap(who(p[1]))} thawed out!` : `${cap(who(p[1]))} was cured of its ${p[2]}.`;
    case 'cant': return `${cap(who(p[1]))} ${CANT[p[2]] || 'can\'t move!'}`;
    case '-boost': case '-unboost': {
      const n = Number(p[3]); if (!n) return null;
      const up = t === '-boost';
      const word = up ? (n >= 3 ? 'rose drastically' : n === 2 ? 'rose sharply' : 'rose') : (n >= 3 ? 'severely fell' : n === 2 ? 'harshly fell' : 'fell');
      return `${cap(who(p[1]))}'s ${STAT[p[2]] || p[2]} ${word}!`;
    }
    case '-start': {
      const e = clean(p[2]);
      if (e === 'confusion') return `${cap(who(p[1]))} became confused${p.includes('[fatigue]') ? ' due to fatigue' : ''}!`;
      if (e === 'Substitute') return `${cap(who(p[1]))} put in a substitute!`;
      if (e === 'Leech Seed') return `${cap(who(p[1]))} was seeded!`;
      if (e === 'typechange') return null;
      return `${cap(who(p[1]))}: ${e}!`;
    }
    case '-end': {
      const e = clean(p[2]);
      if (e === 'confusion') return `${cap(who(p[1]))} snapped out of its confusion!`;
      if (e === 'Substitute') return `${cap(who(p[1]))}'s substitute faded!`;
      if (p.includes('[partiallytrapped]') || TRAP[e]) return `${cap(who(p[1]))} was freed from ${e}!`;
      return null;
    }
    case '-activate': {
      const e = clean(p[2]);
      const of = (p.find(x => x.startsWith('[of] ')) || '').slice(5);
      if (TRAP[e]) return TRAP[e](cap(who(p[1])), who(of) || 'the attacker');
      if (e === 'confusion') return `${cap(who(p[1]))} is confused!`;
      if (e === 'Protect' || e === 'Detect') return `${cap(who(p[1]))} protected itself!`;
      return null;
    }
    case '-singleturn': return /Protect|Detect/.test(p[2]) ? `${cap(who(p[1]))} protected itself!` : null;
    case '-sidestart': return `${clean(p[2])} went up on ${p[1].startsWith('p1') ? 'your' : 'the foe\'s'} side!`;
    case '-sideend': return `${p[1].startsWith('p1') ? 'Your' : 'The foe\'s'} ${clean(p[2])} wore off!`;
    case '-weather': return p.includes('[upkeep]') ? null : p[1] === 'none' ? 'The weather cleared up.' : `The weather became ${p[1].replace(/Dance$/, '')}!`;
    case '-fieldstart': return `${clean(p[1])} took effect!`;
    case '-fieldend': return `${clean(p[1])} wore off.`;
    case '-ability': return `${cap(who(p[1]))}'s ${p[2]}!`;
    case '-enditem': return p.includes('[eat]') ? `${cap(who(p[1]))} ate its ${p[2]}!` : `${cap(who(p[1]))}'s ${p[2]} was used up.`;
    case '-heal': return from === 'Leftovers' ? `${cap(who(p[1]))} restored a little HP with its Leftovers!`
      : from === 'drain' ? `${cap(who(p[1]))} had its energy drained!` : `${cap(who(p[1]))} restored HP.`;
    case '-damage': {
      if (!from) return null;
      const w = cap(who(p[1]));
      if (from === 'brn') return `${w} was hurt by its burn!`;
      if (from === 'psn' || from === 'tox') return `${w} was hurt by poison!`;
      if (from === 'Recoil') return `${w} was damaged by the recoil!`;
      if (from === 'confusion') return 'It hurt itself in its confusion!';
      if (from === 'Stealth Rock') return `Pointed stones dug into ${who(p[1])}!`;
      if (from === 'Spikes') return `${w} was hurt by the spikes!`;
      if (from === 'Leech Seed') return `${w}'s health is sapped by Leech Seed!`;
      return `${w} was hurt by ${from}!`;
    }
    case '-prepare': return `${cap(who(p[1]))} is charging up ${p[2]}!`;
    default: return null;
  }
}
function readable(lines) {
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].startsWith('|split|')) { i++; continue; }  // skip the secret copy; the public one follows
    const s = fmt(lines[i]);
    if (s && out[out.length - 1] !== s) out.push(s);
  }
  return out;
}

// ------------------------------------------------------------------ view --
function view(b, sent) {
  const side = s => s.pokemon.slice().sort((x, y) => x.ankimonIndex - y.ankimonIndex).map(p => ({
    i: p.ankimonIndex, hp: p.hp, maxhp: p.maxhp, status: p.status || null, fainted: !!p.fainted,
    active: !!p.isActive,
    vol: p.isActive ? Object.keys(p.volatiles) : [],         // confusion, partiallytrapped, leechseed...
    boosts: p.isActive ? p.boosts : null}));
  const a = active(b.p1);
  const req = b.p1.activeRequest && b.p1.activeRequest.active ? b.p1.activeRequest.active[0].moves : [];
  const moves = a ? a.moveSlots.map(ms => ({id: ms.id, pp: ms.pp, maxpp: ms.maxpp})) : [];
  const locked = !!(a && req.length === 1 && a.moveSlots.length > 1);
  return {ok: true, turn: b.turn, ended: !!b.ended, winner: b.winner === 'You' ? 'p1' : b.winner === 'Leader' ? 'p2' : null,
    p1: side(b.p1), p2: side(b.p2), moves, locked, log: readable(b.log.slice(sent))};
}


// Planning PLAYER (tuning only): same rollouts from side one's point of view.
function planChoiceP1(b, rollouts = 3, horizon = 8) {
  const opts = usableMoves(b.p1);
  if (opts.length <= 1) return opts.length ? 'move ' + opts[0].i : 'default';
  const snap = b.toJSON();
  let best = opts[0], bv = -Infinity;
  for (const o of opts) {
    let tot = 0;
    for (let r = 0; r < rollouts; r++) {
      const c = Battle.fromJSON(snap);
      c.log = c.log.slice(); c.resetRNG(PRNG.generateSeed()); c.sentLogPos = c.log.length;
      try {
        mc(c, 'move ' + o.i, strongest(c.p2, c.p1));
        for (let t = 1; t < horizon && !c.ended; t++) {
          if (c.p1.requestState === 'switch' || c.p2.requestState === 'switch') break;
          mc(c, strongest(c.p1, c.p2), strongest(c.p2, c.p1));
        }
      } catch (e) {}
      tot += score(c);                 // score is from the leader's view: the PLAYER maximises it
    }
    if (tot > bv) { bv = tot; best = o; }
  }
  return 'move ' + best.i;
}
module.exports = {ctx, cleanSet, newBattle, carryOver, mc, active, usableMoves, nextSwitch, settleSwitches,
  estDamage, strongest, randomChoice, score, planChoice, planChoiceP1, fmt, readable, view};
