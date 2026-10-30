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
const {Battle, Dex, Teams, PRNG, Side} = require('@pkmn/sim');
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
    ivs: stat(s.ivs, 0, 31, 15), evs: stat(s.evs, 0, 252, 0), moves,
    gigantamax: !!s.gigantamax,
    teraType: (s.teraType && dex.types.get(s.teraType).exists) ? dex.types.get(s.teraType).name : undefined};
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
  b.sides.forEach((side, si) => side.pokemon.forEach((p, i) => {
    p.ankimonTera = !!(([t1, t2][si] || [])[i] || {}).canTera;      // set by Ankimon (gym_showdown)
    p.ankimonMega = !!(([t1, t2][si] || [])[i] || {}).mega;         // today's Mega / a leader's (functions/mega.py)
    // Gen 9 keeps move-based Megas off: let Ankimon's Rayquaza (Dragon Key) through
    if (p.ankimonMega && !p.canMegaEvo && p.baseSpecies.name === 'Rayquaza' && p.baseMoves.includes('dragonascent'))
      p.canMegaEvo = 'Rayquaza-Mega';
  }));
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
  const snap = snapshot(b);
  let best = opts[0], bv = Infinity;
  for (const o of opts) {
    let tot = 0;
    for (let r = 0; r < rollouts; r++) {
      const c = Battle.fromJSON(snap);
      if (ctx.totem) totemLock(c);
      if (ctx.titan) titanLock(c);
      if (ctx.guard) guardLock(c);
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
const ctx = {leader: 'The leader', wild: false, dynamax: null, tera: null, titan: null};
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
      : ctx.wild ? `A wild ${p[1].split(': ')[1]} appeared!`
      : ctx.titan ? `The Titan ${p[1].split(': ')[1]} appeared!`
      : ctx.totem ? (!/^Totem /.test(p[1].split(': ')[1]) ? `${p[1].split(': ')[1]} answered the call!`
                     : ctx.totem.intro ? (ctx.totem.intro = false, `${p[1].split(': ')[1]} appeared!`)
                     : `${p[1].split(': ')[1]} is back in the fight!`)
      : `${ctx.leader} sent out ${p[1].split(': ')[1]}!`;
    case '-message': return p[1] || null;
    case '-zpower': return `${cap(who(p[1]))} surrounded itself with its Z-Power!`;
    case 'detailschange': {               // daily Megas: "your Charizard became Mega Charizard X!"
      const sp = (p[2] || '').split(',')[0];
      if (!/-(Mega|Primal)/.test(sp)) return null;
      const nm = /-Primal$/.test(sp) ? 'Primal ' + sp.replace(/-Primal$/, '') : 'Mega ' + sp.replace(/-Mega-?/, ' ').trim();
      return `${cap(who(p[1]))} became ${nm}!`;
    }
    case '-terastallize': return `${cap(who(p[1]))} Terastallized into the ${p[2]} type!`;
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
      if (e === 'Dynamax') return p.includes('Gmax') ? `${cap(who(p[1]))} Gigantamaxed!` : `${cap(who(p[1]))} Dynamaxed!`;
      return `${cap(who(p[1]))}: ${e}!`;
    }
    case '-end': {
      const e = clean(p[2]);
      if (e === 'confusion') return `${cap(who(p[1]))} snapped out of its confusion!`;
      if (e === 'Substitute') return `${cap(who(p[1]))}'s substitute faded!`;
      if (e === 'Dynamax') return `${cap(who(p[1]))} returned to its normal size.`;
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
    case '-heal': if (p.includes('[silent]')) return null;   // e.g. Dynamax doubling HP
      return from === 'Leftovers' ? `${cap(who(p[1]))} restored a little HP with its Leftovers!`
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
  const moves = a ? a.moveSlots.map(ms => ({id: ms.id, name: ms.move, pp: ms.pp, maxpp: ms.maxpp})) : [];
  const locked = !!(a && req.length === 1 && a.moveSlots.length > 1);
  return {ok: true, turn: b.turn, ended: !!b.ended, winner: b.winner === 'You' ? 'p1' : b.winner === 'Leader' ? 'p2' : null,
    p1: side(b.p1), p2: side(b.p2), moves, locked, z: zView(b), zused: !!b.p1.zMoveUsed,
    dmax: dmaxView(b), tera: teraView(b), canswitch: canSwitch(b.p1),
    log: readable(b.log.slice(sent))};
}


// --------------------------------------------------------------- Dynamax --
// Showdown has Dynamax (Max Moves, double HP for 3 turns, G-Max forms) but only
// lets Gen 8 battles use it. Ankimon battles are Gen 9, so the gate opens for
// the sides ctx.dynamax allows ({p1, p2}; set by dmaxStart before newBattle).
// Once per battle is still Showdown's own rule.
const _canDynamaxNow = Side.prototype.canDynamaxNow;
Side.prototype.canDynamaxNow = function () {
  if (this.battle.gen !== 8 && ctx.dynamax) return !!ctx.dynamax[this.id] && !this.dynamaxUsed;
  return _canDynamaxNow.call(this);
};
function dmaxStart(cfg) {                  // {p1: bool, p2: bool} or null
  ctx.dynamax = cfg && (cfg.p1 || cfg.p2) ? {p1: !!cfg.p1, p2: !!cfg.p2} : null;
}
// After newBattle: Gen 9 marks every side's Dynamax as already used; clear it
// for the sides allowed to, so the engine's own flag means once per battle.
function dmaxReady(b) {
  if (!ctx.dynamax) return;
  let changed = false;
  for (const side of b.sides) if (ctx.dynamax[side.id] && side.dynamaxUsed) { side.dynamaxUsed = false; changed = true; }
  if (changed && !b.ended) b.makeRequest();
}
function canDmax(side) {
  const r = side.activeRequest;
  return !!(r && r.active && r.active[0] && r.active[0].canDynamax);
}
function isDmaxed(p) { return !!(p && p.volatiles && p.volatiles['dynamax']); }
// What each Max Move really is, for the battle window: its power (from the
// move it replaces) and its side effect, or Max Guard for a status move.
function maxInfo(baseId, maxId) {
  const base = dex.moves.get(baseId), mx = dex.moves.get(maxId);
  const power = base.category === 'Status' ? 0 : ((base.maxMove && base.maxMove.basePower) || mx.basePower || 0);
  const effect = String(mx.shortDesc || mx.desc || '').replace(/^Base move affects power\.\s*/, '');
  return {id: base.id, name: mx.name, base: base.name, type: mx.type, category: base.category === 'Status' ? 'Status' : base.category,
    power, basePower: base.basePower || 0, effect};
}
function dmaxView(b) {
  const a = active(b.p1), f = active(b.p2);
  const r = b.p1.activeRequest && b.p1.activeRequest.active && b.p1.activeRequest.active[0];
  const mm = r && r.maxMoves && r.maxMoves.maxMoves;
  const moves = (mm && r.moves) ? r.moves.map((m, i) => (mm[i] ? maxInfo(m.id, mm[i].move) : null)).filter(Boolean) : [];
  const turns = isDmaxed(a) ? Math.max(1, 3 - (a.volatiles['dynamax'].turns || 0)) : 0;   // Showdown counts up to 3
  const allowed = !!(ctx.dynamax && ctx.dynamax.p1);
  return {allowed, can: canDmax(b.p1), active: isDmaxed(a), turns,
    gmax: !!(r && r.maxMoves && r.maxMoves.gigantamax), used: allowed && !!b.p1.dynamaxUsed,
    foe: isDmaxed(f), moves};
}
// Gym leaders Dynamax their ace - the last Pokemon they send out - as in
// Sword/Shield (a legendary on its own Dynamaxes on the first turn).
function dmaxLeader(b, c2) {
  if (!ctx.dynamax || !ctx.dynamax.p2 || !/^move \d+$/.test(c2 || '') || !canDmax(b.p2)) return c2;
  const left = b.p2.pokemon.filter(p => !p.fainted).length;
  return left === 1 ? c2 + ' dynamax' : c2;
}
// Auto-battle: Dynamax when the leader's ace is out (last Pokemon or already
// Dynamaxed), or when this is your last Pokemon - with the hardest-hitting move.
function autoDmax(b) {
  if (!canDmax(b.p1)) return null;
  const me = active(b.p1), foe = active(b.p2);
  if (!me || !foe) return null;
  const foeLast = b.p2.pokemon.filter(p => !p.fainted).length === 1;
  const meLast = b.p1.pokemon.filter(p => !p.fainted).length === 1;
  if (!(foeLast || meLast || isDmaxed(foe))) return null;
  let best = null, bv = -1;
  for (const o of usableMoves(b.p1)) {
    if (dex.moves.get(o.id).category === 'Status') continue;
    const d = estDamage(me, foe, o.id);
    if (d > bv) { bv = d; best = o; }
  }
  return best ? 'move ' + best.i + ' dynamax' : null;
}

// ------------------------------------------------------------------ Tera --
// Gen 9 battles let every Pokemon Terastallize (Showdown's own rule, once per
// battle, Tera type = set.teraType or its first type). Ankimon only lets the
// sides ctx.tera allows do it (Paldea; tera.py) - nobody else ever asks.
function teraStart(cfg) {                  // {p1: bool, p2: bool} or null
  ctx.tera = cfg && (cfg.p1 || cfg.p2) ? {p1: !!cfg.p1, p2: !!cfg.p2} : null;
}
// After newBattle: only Pokemon Ankimon allows (a held Tera Shard; a leader's
// ace) keep the engine's Tera option - Gen 9 would offer it to everyone.
function teraReady(b) {
  let changed = false;
  for (const side of b.sides) for (const p of side.pokemon) {
    if (!(ctx.tera && ctx.tera[side.id] && p.ankimonTera) && p.canTerastallize) { p.canTerastallize = null; changed = true; }
  }
  if (changed && !b.ended) b.makeRequest();
}
// The move a Terastallizing Pokemon gives up for Tera Blast: its weakest attack
// (variable-power moves count as 60), or its last move if it has no attack.
function teraWorstSlot(p) {
  let best = -1, bp = Infinity;
  p.moveSlots.forEach((ms, i) => {
    const mv = dex.moves.get(ms.id);
    if (!mv.exists || mv.category === 'Status') return;
    const pw = mv.basePower > 1 ? mv.basePower : 60;
    if (pw < bp) { bp = pw; best = i; }
  });
  return best >= 0 ? best : p.moveSlots.length - 1;
}
// Slot i becomes Tera Blast (fresh PP) for the rest of the battle. You: the move
// you pick with Tera on, swapped BEFORE the turn so Tera Blast is what's used.
function teraBlastAt(b, side, i) {
  const p = active(side);
  if (!p || p.ankimonBlast || i < 0 || i >= p.moveSlots.length) return;
  p.ankimonBlast = true;
  if (p.moveSlots[i].id === 'terablast') return;
  const old = p.moveSlots[i].move, tb = dex.moves.get('terablast');
  const slot = {move: tb.name, id: tb.id, pp: tb.pp, maxpp: tb.pp, target: tb.target, disabled: false, used: false};
  p.moveSlots[i] = slot;
  if (p.baseMoveSlots && p.baseMoveSlots[i]) p.baseMoveSlots[i] = Object.assign({}, slot);
  b.add('-message', `${side.id === 'p1' ? 'Your' : 'The foe\'s'} ${p.name}'s ${old} became Tera Blast (${p.teraType})!`);
}
// After every turn: a leader who just Terastallized swaps its weakest attack
// for Tera Blast (yours was swapped before the turn).
function teraBlastSwap(b) {
  for (const side of b.sides) {
    const p = active(side);
    if (!p || !p.terastallized || p.ankimonBlast) continue;
    if (p.moveSlots.some(ms => ms.id === 'terablast')) { p.ankimonBlast = true; continue; }
    teraBlastAt(b, side, teraWorstSlot(p));
  }
}
function canTera(side) {
  if (!ctx.tera || !ctx.tera[side.id]) return null;
  const r = side.activeRequest;
  return (r && r.active && r.active[0] && r.active[0].canTerastallize) || null;   // the Tera type
}
// Defending as a single type: what hits it hard, what it shrugs off.
function typeMatchups(type) {
  const t = dex.types.get(type);
  const out = {weak: [], resist: [], immune: []};
  if (!t.exists) return out;
  for (const [atk, code] of Object.entries(t.damageTaken || {})) {
    if (!dex.types.get(atk).exists) continue;               // skips prankster / sandstorm etc.
    if (code === 1) out.weak.push(atk); else if (code === 2) out.resist.push(atk); else if (code === 3) out.immune.push(atk);
  }
  return out;
}
function teraView(b) {
  const a = active(b.p1), f = active(b.p2);
  const can = canTera(b.p1), act = (a && a.terastallized) || null;
  const type = act || can || null;
  const w = a && !a.moveSlots.some(ms => ms.id === 'terablast') ? teraWorstSlot(a) : -1;
  return {allowed: !!(ctx.tera && ctx.tera.p1), can, active: act,
    blastFrom: (w >= 0 && a.moveSlots[w]) ? a.moveSlots[w].move : '',
    used: b.p1.pokemon.some(p => p.terastallized) ||
      !!(ctx.tera && ctx.tera.p1 && b.p1.pokemon.every(p => p.canTerastallize === null)),
    // for the window's explanation: your Pokemon's own types and the Tera type's matchups
    name: a ? a.name : '', types: a ? a.species.types.slice() : [], type,
    matchups: type ? typeMatchups(type) : null,
    knowsTeraBlast: !!(a && a.moveSlots.some(ms => ms.id === 'terablast')),
    foe: (f && f.terastallized) || null, foeName: f ? f.name : '',
    foeTypes: f ? f.species.types.slice() : [],
    foeMatchups: (f && f.terastallized) ? typeMatchups(f.terastallized) : null};
}
// Leaders Terastallize their ace (the last Pokemon they send out) into its
// Tera type - Sc/Vi gym leaders' trademark (their gym's type).
function teraLeader(b, c2) {
  if (!/^move \d+$/.test(c2 || '') || !canTera(b.p2)) return c2;
  return b.p2.pokemon.filter(p => !p.fainted).length === 1 ? c2 + ' terastallize' : c2;
}
// Auto-battle: Terastallize against the leader's ace, with your last Pokemon,
// or once the leader has - with the hardest-hitting move.
function autoTera(b) {
  if (!canTera(b.p1)) return null;
  const me = active(b.p1), foe = active(b.p2);
  if (!me || !foe) return null;
  const foeLast = b.p2.pokemon.filter(p => !p.fainted).length === 1;
  const meLast = b.p1.pokemon.filter(p => !p.fainted).length === 1;
  if (!(foeLast || meLast || foe.terastallized)) return null;
  // the move it gives up becomes Tera Blast and is used now: its weakest attack
  return 'move ' + (teraWorstSlot(me) + 1) + ' terastallize';
}

// --------------------------------------------------------------- Z-Moves --
// Showdown offers a Z-Move when your active Pokemon holds a Z-Crystal that
// matches one of its moves, once per battle. Ankimon only asks for one when
// you own the Z-Ring (gym_battle / zmoves.py); leaders never use them.
function zOptions(b) {
  const r = b.p1.activeRequest;
  const a = r && r.active && r.active[0];
  return (a && a.canZMove) || null;
}
function zView(b) {                // [{id, name, ...zInfo}] for the moves that can go Z, or null
  const z = zOptions(b);
  const r = b.p1.activeRequest;
  if (!z || !r || !r.active) return null;
  const out = r.active[0].moves.map((m, i) => (z[i] ? zInfo(m.id, z[i].move) : null)).filter(Boolean);
  return out.length ? out : null;
}
// What the Z-Move really is, for the battle window: an attack's Z power (from
// the move it replaces), or a status move's Z bonus.
const Z_STAT = {atk: 'Attack', def: 'Defense', spa: 'Sp. Atk', spd: 'Sp. Def', spe: 'Speed',
  accuracy: 'accuracy', evasion: 'evasiveness'};
function zInfo(id, zname) {
  const base = dex.moves.get(id);
  const o = {id, name: zname, base: base.name, type: base.type, category: base.category,
    basePower: base.basePower || 0, power: 0, effect: ''};
  if (base.category !== 'Status') {
    o.power = (base.zMove && base.zMove.basePower) || 0;
  } else {
    const z = base.zMove || {};
    if (z.boost) {
      const ks = Object.keys(z.boost);
      const n = z.boost[ks[0]];
      const same = ks.every(k => z.boost[k] === n);
      o.effect = (same ? ks.map(k => Z_STAT[k] || k).join(', ') + ' +' + n
        : ks.map(k => (Z_STAT[k] || k) + ' +' + z.boost[k]).join(', ')) + ', then ' + base.name;
    } else {
      o.effect = ({
        clearnegativeboost: 'clears your lowered stats, then ' + base.name,
        heal: 'fully restores your HP, then ' + base.name,
        crit2: 'raises your critical-hit ratio by 2, then ' + base.name,
        healreplacement: base.name + ', and the next Pokemon you send in is fully healed',
        curse: 'Ghost types: fully restores HP first; others: Attack +1 first',
        redirect: base.name + ' (its Z bonus does nothing one-on-one)',
      })[z.effect] || base.name + ' (no extra Z effect)';
    }
  }
  return o;
}
// Auto-battle: spend it on the leader's last Pokemon, when yours is low, or
// when the foe could knock yours out this turn - on the hardest-hitting attack.
function autoZ(b) {
  const z = zOptions(b);
  const me = active(b.p1), foe = active(b.p2);
  if (!z || !me || !foe) return null;
  let best = null, bv = -1;
  for (const o of usableMoves(b.p1)) {
    if (!z[o.i - 1] || dex.moves.get(o.id).category === 'Status') continue;
    const d = estDamage(me, foe, o.id);
    if (d > bv) { bv = d; best = o; }
  }
  if (!best) return null;
  const foeLast = b.p2.pokemon.filter(p => !p.fainted).length === 1;
  const low = me.hp <= me.maxhp / 3;
  const danger = foe.moveSlots.some(ms => estDamage(foe, me, ms.id) >= me.hp);
  return (foeLast || low || danger) ? 'move ' + best.i + ' zmove' : null;
}

// ---------------------------------------------------------------- totems --
// Alola totem trials ({cmd:"start", ..., totem:{aura:{def:1}}}): p2 is the
// totem (team slot 0) followed by its reinforcements, in order.
//  - the totem starts alone, with its aura (stat boosts);
//  - it can't be knocked out early: while it still has help to call, no damage
//    takes it below 30% HP (totemLock) - it holds there;
//  - at 30% HP or less it withdraws and calls for help: the first reinforcement;
//  - the reinforcements come one after another;
//  - after the last one faints the totem returns at half HP, aura restored;
//  - the totem fainting ends the battle, whatever is left.
const TOTEM_WITHDRAW = 0.30, TOTEM_RETURN = 0.50;
const STAT_IDS = ['atk', 'def', 'spa', 'spd', 'spe'];
function totemStart(b, cfg) {
  ctx.totem = cfg ? {aura: cfg.aura || {}, wasActive: true, intro: true} : null;
  if (!ctx.totem) return;
  totemLock(b);
  const t = totemMon(b);
  if (t && t.isActive) totemAura(b, t, `${t.name}'s aura flared to life!`);
  b.sentLogPos = b.log.length;
}
function totemMon(b) { return b.p2.pokemon.find(p => p.ankimonIndex === 0); }
// Anti one-shot: while the totem still has reinforcements to call (and isn't
// trapped, so it can actually withdraw), damage stops at 30% of its HP. It
// calls for help next turn. Battle clones for planning get it again.
// Battle state for planning copies. The totem lock's handler (b.events) can't
// be serialized, so it's set aside while copying; copies re-attach it.
function snapshot(b) {
  const ev = b.events;
  b.events = null;
  try { return b.toJSON(); } finally { b.events = ev; }
}
function totemLock(b) {
  b.onEvent('Damage', b.format, (damage, target) => {
    if (!ctx.totem || !target || typeof damage !== 'number') return damage;
    const bb = target.battle;
    if (target.side !== bb.p2 || target.ankimonIndex !== 0) return damage;
    if (!totemAllies(bb).length) return damage;
    const req = bb.p2.activeRequest && bb.p2.activeRequest.active && bb.p2.activeRequest.active[0];
    if (req && (req.trapped || req.maybeTrapped)) return damage;
    const lock = Math.max(1, Math.floor(target.maxhp * TOTEM_WITHDRAW));
    if (target.hp - damage >= lock) return damage;
    const left = Math.max(0, target.hp - lock);
    bb.add('-message', `${target.name} held on!`);
    return left;
  });
}
function totemAllies(b) {          // reinforcements still able to come in, in order
  return b.p2.pokemon.filter(p => p.ankimonIndex > 0 && !p.fainted && !p.isActive)
    .sort((x, y) => x.ankimonIndex - y.ankimonIndex);
}
function totemAura(b, t, msg) {
  b.add('-message', msg);
  for (const k of STAT_IDS) {
    const n = ctx.totem.aura[k];
    if (!n) continue;
    const before = t.boosts[k];
    t.boostBy({[k]: n});                       // stat stages, capped at +6
    if (t.boosts[k] !== before) b.add('-boost', t, k, t.boosts[k] - before);
  }
}
// The leader's choice this turn: withdraw the worn-down totem, or null (normal move).
function totemChoice(b) {
  const T = ctx.totem;
  if (!T || b.ended) return null;
  const t = totemMon(b);
  if (!t || !t.isActive || t.fainted || t.hp > t.maxhp * TOTEM_WITHDRAW) return null;
  const next = totemAllies(b)[0];
  if (!next) return null;
  const req = b.p2.activeRequest && b.p2.activeRequest.active && b.p2.activeRequest.active[0];
  if (!req || req.trapped || req.maybeTrapped) return null;   // can't withdraw while trapped
  b.add('-message', `${t.name} called for help!`);
  return 'switch ' + (b.p2.pokemon.indexOf(next) + 1);
}
// After every step: a fainted totem ends it; a totem that just came back in
// gets its aura again (and half HP once its reinforcements are gone).
function totemCheck(b) {
  const T = ctx.totem;
  if (!T || b.ended) return;
  const t = totemMon(b);
  if (!t) return;
  if (t.fainted) { b.win('p1'); return; }
  if (t.isActive && !T.wasActive) {
    if (!totemAllies(b).length && t.hp < Math.floor(t.maxhp * TOTEM_RETURN)) t.sethp(Math.floor(t.maxhp * TOTEM_RETURN));
    totemAura(b, t, `${t.name}'s aura is still flaring!`);
  }
  T.wasActive = t.isActive;
}
// Forced replacements for the leader: next reinforcement, the totem last.
function totemNextSwitch(b) {
  const next = totemAllies(b)[0];
  const t = totemMon(b);
  if (next) {
    if (t) b.add('-message', `${t.name} called for help!`);
    return 'switch ' + (b.p2.pokemon.indexOf(next) + 1);
  }
  if (t && !t.fainted && !t.isActive) return 'switch ' + (b.p2.pokemon.indexOf(t) + 1);
  return 'pass';
}
// ---------------------------------------------------------------- Titans --
// Paldea's Titans ({cmd:"start", ..., titan:{aura:{def:1}, power:{atk:1, spa:1}}}):
// p2 is the Titan alone. It starts with its aura; the first time it would
// faint it holds at 1 HP, eats a Herba Mystica and comes back at full HP with
// its power-up (Sc/Vi's second round). The second time it faints, you win.
// Shares the totem helpers (aura / damage hook).
function titanStart(b, cfg) {
  ctx.titan = cfg ? {aura: cfg.aura || {}, power: cfg.power || {}, phase: 1, pending: false} : null;
  if (!ctx.titan) return;
  titanLock(b);
  const t = b.p2.pokemon.find(p => p.ankimonIndex === 0);
  if (t && t.isActive) titanBoost(b, t, ctx.titan.aura, `${t.name} towers over you!`);
  b.sentLogPos = b.log.length;
}
function titanBoost(b, t, boosts, msg) {
  b.add('-message', msg);
  for (const k of STAT_IDS) {
    const n = boosts[k];
    if (!n) continue;
    const before = t.boosts[k];
    t.boostBy({[k]: n});
    if (t.boosts[k] !== before) b.add('-boost', t, k, t.boosts[k] - before);
  }
}
// Battle HP (user 2026-10-15): gym-style fights run at x2 HP for everyone, so
// one move rarely knocks anything out (one-shots in ~13% of +/-5-level
// matchups -> ~1-2%: balance_sim/hp_inflation.py). baseMaxhp too, or
// Dynamax ending would drop it back. Ankimon reads HP back divided by it.
function hpScale(b, mult) {
  ctx.hpmult = mult && mult > 0 ? mult : 1;
  if (ctx.hpmult === 1) return;
  for (const side of b.sides) for (const p of side.pokemon) {
    p.baseMaxhp = Math.round(p.baseMaxhp * ctx.hpmult);
    p.maxhp = Math.round(p.maxhp * ctx.hpmult);
    p.hp = p.hp > 0 ? Math.max(1, Math.round(p.hp * ctx.hpmult)) : 0;
  }
}
// Hidden boss guard (user 2026-10-15): wild legendaries (expeditions, roaming
// and one-time encounters), totems and Titans take 25% less damage from moves.
// Never shown; it's battle-only, so a caught Pokemon doesn't keep it.
function guardStart(b, cfg) {
  ctx.guard = cfg ? {mult: cfg.mult || 0.75} : null;
  if (ctx.guard) guardLock(b);
}
function guardLock(b) {
  b.onEvent('Damage', b.format, (damage, target, source, effect) => {
    const g = ctx.guard;
    if (!g || !target || typeof damage !== 'number' || damage <= 0) return damage;
    const bb = target.battle;
    if (target.side !== bb.p2 || target.ankimonIndex !== 0) return damage;
    if (!effect || effect.effectType !== 'Move') return damage;     // moves only
    return Math.max(1, Math.floor(damage * g.mult));
  });
}
function titanLock(b) {
  b.onEvent('Damage', b.format, (damage, target) => {
    const T = ctx.titan;
    if (!T || T.phase !== 1 || !target || typeof damage !== 'number') return damage;
    const bb = target.battle;
    if (target.side !== bb.p2 || target.ankimonIndex !== 0) return damage;
    if (target.hp - damage >= 1) return damage;
    T.pending = true;                          // round two after this turn
    return Math.max(0, target.hp - 1);
  });
}
function titanSettle(b) {
  const T = ctx.titan;
  if (!T || !T.pending || b.ended) return;
  T.pending = false;
  T.phase = 2;
  const t = b.p2.pokemon.find(p => p.ankimonIndex === 0);
  if (!t || t.fainted) return;
  t.sethp(t.maxhp);
  titanBoost(b, t, T.power, `${t.name} ate a Herba Mystica and grew even stronger! Its HP was fully restored!`);
}

function totemSettle(b) {
  let guard = 0;
  totemCheck(b);
  while (!b.ended && guard++ < 8 && (b.p1.requestState === 'switch' || b.p2.requestState === 'switch')) {
    mc(b, b.p1.requestState === 'switch' ? nextSwitch(b.p1) : 'pass',
       b.p2.requestState === 'switch' ? totemNextSwitch(b) : 'pass');
    totemCheck(b);
  }
}

// Planning PLAYER (tuning only): same rollouts from side one's point of view.
function planChoiceP1(b, rollouts = 3, horizon = 8) {
  const opts = usableMoves(b.p1);
  if (opts.length <= 1) return opts.length ? 'move ' + opts[0].i : 'default';
  const snap = snapshot(b);
  let best = opts[0], bv = -Infinity;
  for (const o of opts) {
    let tot = 0;
    for (let r = 0; r < rollouts; r++) {
      const c = Battle.fromJSON(snap);
      if (ctx.totem) totemLock(c);
      if (ctx.titan) titanLock(c);
      if (ctx.guard) guardLock(c);
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

// ------------------------------------------------------------- switching --
// You: switch to a team member that's still standing - it uses your turn.
// Leaders that switch (Elite Four, Champions, rematches: ctx.aiswitch = {max,
// gap}) do it at most `max` times a battle, with at least `gap` of their own
// moves between two switches, and only when the look-ahead says the switch-in
// does clearly better than their best move (SWITCH_MARGIN). Faint replacements
// don't count. Everyone else never switches by choice.
const SWITCH_MARGIN = 0.25;        // a quarter of a Pokemon's HP: "might help" isn't enough
function aiSwitchStart(cfg) {
  ctx.aiswitch = cfg ? {max: cfg.max == null ? 3 : +cfg.max, gap: cfg.gap == null ? 5 : +cfg.gap,
                        used: 0, since: null} : null;
}
function canSwitch(side) {
  const req = side.activeRequest;
  if (!req || !req.active || req.forceSwitch || req.wait) return false;
  const a = req.active[0];
  if (a.trapped || a.maybeTrapped) return false;          // Mean Look, Outrage's lock...
  const p = active(side);                                  // mid Fly / Dig / Solar Beam: no
  if (p && (p.getLockedMove() || p.getSemiLockedMove())) return false;
  return side.pokemon.some(p => !p.fainted && !p.isActive);
}
function switchTo(side, k) {         // 'switch N' for team slot k (its original place), or null
  if (!canSwitch(side)) return null;
  const i = side.pokemon.findIndex(p => p.ankimonIndex === +k && !p.fainted && !p.isActive);
  return i < 0 ? null : 'switch ' + (i + 1);
}
function aiSwitch(b, rollouts = 3, horizon = 8) {
  const s = ctx.aiswitch;
  if (!s || s.used >= s.max || (s.since !== null && s.since < s.gap)) return null;
  if (ctx.totem || ctx.titan || !canSwitch(b.p2)) return null;
  const bench = b.p2.pokemon.map((p, i) => ({p, i})).filter(x => !x.p.fainted && !x.p.isActive);
  const opts = usableMoves(b.p2);
  if (!bench.length || !opts.length) return null;
  const snap = snapshot(b);
  const play = c2 => {               // the planning leader's look-ahead, for any first choice
    let tot = 0;
    for (let r = 0; r < rollouts; r++) {
      const c = Battle.fromJSON(snap);
      if (ctx.guard) guardLock(c);
      c.log = c.log.slice(); c.resetRNG(PRNG.generateSeed()); c.sentLogPos = c.log.length;
      try {
        mc(c, strongest(c.p1, c.p2), c2);
        for (let t = 1; t < horizon && !c.ended; t++) {
          if (c.p1.requestState === 'switch' || c.p2.requestState === 'switch') break;
          mc(c, strongest(c.p1, c.p2), strongest(c.p2, c.p1));
        }
      } catch (e) { /* scores where it stopped */ }
      tot += score(c);
    }
    return tot / rollouts;
  };
  let stay = Infinity;
  for (const o of opts) stay = Math.min(stay, play('move ' + o.i));
  let best = null, bv = Infinity;
  for (const x of bench) { const v = play('switch ' + (x.i + 1)); if (v < bv) { bv = v; best = x; } }
  return best && bv < stay - SWITCH_MARGIN ? 'switch ' + (best.i + 1) : null;
}
function aiSwitchNote(c2, lines) {    // after the turn: what the leader did (its log lines)
  const s = ctx.aiswitch;
  if (!s || !c2) return;
  if (/^switch /.test(c2)) { s.used++; s.since = 0; return; }
  // only a move it really used counts (flinched / fully paralyzed / asleep: no;
  // a move called by another - Sleep Talk's - isn't a second one)
  if (s.since !== null && (lines || []).some(l => /^\|move\|p2a: /.test(l) && !/\[from\]/.test(l))) s.since++;
}
// ------------------------------------------------------------ daily Megas --
// A Pokémon Ankimon marks (set.mega: today's Mega, or a rematched leader's) holds
// its Mega Stone and Mega Evolves with its first move; Primal Orbs act on their own.
function canMega(side) {
  const a = side.active[0];
  return !!(a && a.ankimonMega && a.canMegaEvo);
}
function megaChoice(b, side, c) {
  return /^move \d+$/.test(c || '') && canMega(side) ? c + ' mega' : c;
}
module.exports = {ctx, cleanSet, newBattle, carryOver, mc, active, usableMoves, nextSwitch, settleSwitches,
  aiSwitchStart, canSwitch, switchTo, aiSwitch, aiSwitchNote,
  estDamage, strongest, randomChoice, score, planChoice, planChoiceP1, fmt, readable, view,
  totemStart, totemChoice, totemCheck, totemSettle, zOptions, zView, autoZ,
  titanStart, titanSettle, guardStart, guardLock, hpScale,
  dmaxStart, dmaxReady, dmaxView, dmaxLeader, autoDmax, canDmax,
  teraStart, teraReady, teraBlastAt, teraBlastSwap, teraView, teraLeader, autoTera, canTera,
  canMega, megaChoice};
