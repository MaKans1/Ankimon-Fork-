"""
autopick.py - "Choose team for me" in the team picker (user 2026-10-28).

Picks three from the whole PC, with moves for this fight only, and the fight
starts. Good enough rather than perfect (Elite Four and Champions may still
want a hand-picked team):

  1. Moves: from what you could set up yourself - the moves it knows, what Remember
     Attacks offers and, ticked, the TMs you own that it can learn (TMs aren't used
     up), usable at the level it fights at - a spread for this team: its hardest
     hitter, an attack that also does something and two support moves that help
     (best_moves), scored with the type chart and stats.
  2. Every Pokémon is scored against every opponent: how fast it knocks it out
     against how fast it gets knocked out, and who moves first. The best trios
     are the ones with a good answer to each opponent.
  3. With the Showdown engine, the best few trios play quick fights against
     this team and the best record wins (a few seconds).

The picked moves only live on the copies the fight uses: gym_battle never writes
a fight's moves back to the saved Pokémon (records carry "_picked_moves").
"""

import copy
import json
import math
import subprocess
import threading
from itertools import combinations

from aqt import mw
from aqt.qt import QEventLoop, QProgressDialog, Qt, QTimer

from . import gym_battle as GB
from .gym_battle import _log
from .move_card import _cap, _details, multiplier

SHORTLIST = 14          # best single Pokémon carried into trio scoring (+ the top 3 per opponent)
TRIOS = 4               # trios that play quick Showdown fights
FIGHTS = 4              # quick fights per trio
TM_CATEGORY = 37        # items.category_id of TMs (item_window)
# attacks that don't suit a straight fight (charge turns, recharge, self-KO and
# moves that only work in special situations); flags catch the rest
SKIP = {"dreameater", "lastresort", "belch", "synchronoise", "snore", "sleeptalk", "fakeout",
        "firstimpression", "naturalgift", "fling", "spitup", "counter", "mirrorcoat", "metalburst",
        "bide", "endeavor", "comeuppance", "futuresight", "doomdesire", "focuspunch", "steelroller",
        "burnup", "doubleshock", "mindblown", "steelbeam", "finalgambit", "memento", "outrage",
        "thrash", "petaldance", "ragingfury", "uproar", "rollout", "iceball", "chloroblast",
        "explosion", "selfdestruct", "mistyexplosion", "skydrop", "struggle"}
# support moves (best_moves, user 2026-11-02): what a status condition is worth in
# a gym fight, who shrugs it off, healing moves the data doesn't mark, and the least
# a support move must be worth to take a slot from an attack
STATUS_VALUE = {"par": 1.2, "brn": 1.0, "slp": 1.4, "tox": 1.0, "psn": 0.6, "frz": 1.0}
STATUS_IMMUNE = {"par": {"Electric"}, "brn": {"Fire"}, "tox": {"Poison", "Steel"},
                 "psn": {"Poison", "Steel"}, "frz": {"Ice"}}
HEALS = {"synthesis": 1.0, "morningsun": 1.0, "moonlight": 1.0, "shoreup": 1.0, "strengthsap": 0.9,
         "junglehealing": 0.7, "wish": 0.7, "rest": 0.5, "painsplit": 0.5, "ingrain": 0.4, "aquaring": 0.4}
SUPPORT_MIN = 0.3


def _id(m) -> str:
    return "".join(ch for ch in str(m or "").lower() if ch.isalnum())


# ------------------------------------------------------------------ stats --
class _Mon:
    def __init__(self, species, types, level, base, iv, ev, moves):
        self.species, self.level, self.moves = species, int(level), [_id(m) for m in moves or []]
        self.types = [_cap(t) for t in (types if isinstance(types, (list, tuple)) else [types]) if t]
        base, iv, ev = base or {}, iv or {}, ev or {}
        self.stats = {}
        for k in ("hp", "atk", "def", "spa", "spd", "spe"):
            core = (2 * int(base.get(k, 50) or 50) + int(iv.get(k, 15) or 0) + int(ev.get(k, 0) or 0) // 4) \
                * self.level // 100
            self.stats[k] = core + self.level + 10 if k == "hp" else core + 5


def _attack(d) -> bool:
    if not d or str(d.get("category") or "Status") == "Status":
        return False
    if d.get("ohko") or d.get("selfdestruct"):
        return False
    flags = d.get("flags") or {}
    if flags.get("charge") or flags.get("recharge"):
        return False
    return bool(d.get("basePower")) or d.get("damage") == "level"


def _hit(att, dfn, mv) -> float:
    """Expected share of dfn's HP one use of mv takes (accuracy included)."""
    if mv in SKIP:
        return 0.0
    d = _details(mv)
    if not _attack(d):
        return 0.0
    t = _cap(d.get("type")) or "Normal"
    eff = multiplier(mv, t, dfn.types)
    if eff <= 0:
        return 0.0
    acc = 1.0 if d.get("accuracy") is True else float(d.get("accuracy") or 100) / 100.0
    if d.get("damage") == "level":                       # Seismic Toss, Night Shade
        return acc * att.level / max(1, dfn.stats["hp"])
    phys = str(d.get("category")) == "Physical"
    a = att.stats["atk" if phys else "spa"]
    b = dfn.stats["def" if phys else "spd"]
    dmg = ((2 * att.level / 5.0 + 2) * float(d.get("basePower")) * a / max(1, b)) / 50.0 + 2
    mh = d.get("multihit")
    hits = 3.0 if isinstance(mh, list) else float(mh or 1)
    stab = 1.5 if t in att.types else 1.0
    return dmg * hits * stab * eff * acc * 0.925 / max(1, dfn.stats["hp"])


def _duel(me, foe) -> float:
    """> 0: it beats this opponent one on one (log2 of the turns it survives over
    the turns it needs), a little more if it moves first."""
    off = max([_hit(me, foe, m) for m in me.moves] or [0.0])
    dfn = max([_hit(foe, me, m) for m in foe.moves] or [0.0])
    need = 1.0 / off if off > 0 else 64.0
    last = 1.0 / dfn if dfn > 0 else 64.0
    s = math.log2(last / need) + (0.3 if me.stats["spe"] > foe.stats["spe"] else -0.3)
    return max(-4.0, min(4.0, s))


# ------------------------------------------------------------------ moves --
_TM_LEARN = None


def _tm_learnset() -> dict:
    global _TM_LEARN
    if _TM_LEARN is None:
        try:
            from ..resources import pokemon_tm_learnset_path
            _TM_LEARN = json.load(open(pokemon_tm_learnset_path, encoding="utf-8"))
        except Exception:
            _TM_LEARN = {}
    return _TM_LEARN


def owned_tms() -> set:
    try:
        rows = mw.ankimon_db.execute("SELECT item_name FROM items WHERE category_id = ? AND quantity > 0",
                                     (TM_CATEGORY,)).fetchall()
        return {_id(r[0]) for r in rows}
    except Exception:
        return set()


def move_pool(rec, fight_lv, tms=()) -> set:
    """What you could set up yourself: the moves it knows, what Remember Attacks
    offers at its own level and the TMs you own that it can learn - each one usable
    at fight_lv when it fights below its own level (functions/move_seal, as the
    fight itself seals them)."""
    from ..functions import move_seal as MS
    species = str(rec.get("name") or "")
    real = int(rec.get("level") or 1)
    pool = {_id(a) for a in rec.get("attacks") or []}
    # level-up moves: exactly the Remember Attacks list (user 2026-10-30: never a move the
    # player couldn't pick - each move's newest entry from any generation let moves the
    # newest games dropped from a species' level-up list through)
    try:
        from ..functions.learnset_retrieval import get_all_pokemon_moves
        pool |= {_id(m) for m in get_all_pokemon_moves(species, real) or []}
    except Exception:
        pass
    if tms:
        try:
            from ..functions.pokedex_functions import search_pokedex_by_id
            can = {_id(m) for m in _tm_learnset().get(search_pokedex_by_id(rec.get("id"))) or []}
            pool |= set(tms) & can
        except Exception:
            pass
    if fight_lv < real:
        pool = {m for m in pool if MS.required_level(species, m) <= fight_lv}
    return pool


def _lands(status, d, mv, foe) -> bool:
    """A status from mv - its own, or an attack's added effect - can land on foe."""
    if set(foe.types) & STATUS_IMMUNE.get(status, set()):
        return False
    if (d.get("flags") or {}).get("powder") and "Grass" in foe.types:
        return False
    if str(d.get("category")) != "Status" or d.get("ignoreImmunity") is False:   # Thunder Wave on Ground
        return multiplier(mv, _cap(d.get("type")) or "Normal", foe.types) > 0
    return True


def _utility(mv, foes) -> float:
    """What an attack does besides damage (0: nothing that earns it the slot):
    moving first, draining, a likely status, flinch or stat drop on the foe, or a
    boost for itself. Drawbacks (Close Combat) and switching out don't count."""
    d = _details(mv)
    if mv in SKIP or not _attack(d):
        return 0.0
    v = 0.5 if int(d.get("priority") or 0) > 0 else 0.0
    if d.get("drain"):
        v += 0.4
    for s in d.get("secondaries") or ([d["secondary"]] if d.get("secondary") else []):
        ch = float(s.get("chance") or 100) / 100.0
        if ch < 0.3:
            continue
        st = s.get("status")
        if st:
            v += ch * STATUS_VALUE.get(st, 0.5) * sum(_lands(st, d, mv, f) for f in foes) / max(1, len(foes))
        v += ch * 0.3 * sum(-x for x in (s.get("boosts") or {}).values() if x < 0)
        v += ch * 0.4 * sum(x for x in ((s.get("self") or {}).get("boosts") or {}).values() if x > 0)
        if s.get("volatileStatus") in ("flinch", "confusion"):
            v += ch * 0.4
    return v


def _support(me, foes, mv):
    """(worth, kind) of a status move in this fight: raising its attacking stat or
    speed, healing, a status the foes don't shrug off, lowering their stats,
    screens, Leech Seed... (0, "") when it wouldn't help."""
    d = _details(mv)
    if mv in SKIP or not d or str(d.get("category") or "") != "Status":
        return 0.0, ""
    acc = 1.0 if d.get("accuracy") is True else float(d.get("accuracy") or 100) / 100.0
    share = lambda ok: sum(1 for f in foes if ok(f)) / float(max(1, len(foes)))
    heal = d.get("heal")
    if mv in HEALS or heal:
        return (HEALS[mv] if mv in HEALS else 2.0 * heal[0] / max(1, heal[1])), "heal"
    boosts = d.get("boosts") or {}
    on_self = str(d.get("target") or "") in ("self", "adjacentAllyOrSelf", "allies", "allySide")
    if mv == "curse":                                   # a Ghost's Curse hurts itself instead
        if "Ghost" in me.types:
            return 0.0, ""
        on_self = True
    phys = me.stats["atk"] >= me.stats["spa"]                 # how it hits
    hard = share(lambda f: f.stats["atk"] >= f.stats["spa"])  # how many of them hit physically
    if boosts and on_self:
        w = {"atk": 1.0 if phys else 0.1, "spa": 0.1 if phys else 1.0, "spe": 0.6,
             "def": 0.15 + 0.5 * hard, "spd": 0.65 - 0.5 * hard, "accuracy": 0.2, "evasion": 0.3}
        return min(2.2, sum(w.get(k, 0) * x for k, x in boosts.items())), "setup"
    if d.get("status"):
        st = d["status"]
        return STATUS_VALUE.get(st, 0.5) * acc * share(lambda f: _lands(st, d, mv, f)), "status"
    if boosts:                                          # their stats down (Swagger's rise counts against)
        w = {"atk": 0.35 * hard, "spa": 0.35 * (1 - hard), "def": 0.3 if phys else 0.05,
             "spd": 0.05 if phys else 0.3, "spe": 0.35, "accuracy": 0.3, "evasion": 0.1}
        v = acc * sum(-w.get(k, 0) * x for k, x in boosts.items())
        if d.get("volatileStatus") == "confusion":
            v += 0.4 * acc
        return v, "drop"
    vol = d.get("volatileStatus")
    if vol == "leechseed":
        return 0.8 * acc * share(lambda f: "Grass" not in f.types), "heal"
    if vol == "confusion":
        return 0.4 * acc, "status"
    if vol == "substitute":
        return 0.5, "setup"
    side = d.get("sideCondition")
    if side in ("reflect", "lightscreen", "auroraveil"):
        return {"reflect": 0.2 + 0.6 * hard, "lightscreen": 0.8 - 0.6 * hard}.get(side, 0.6), "screen"
    if side == "tailwind":
        return 0.5, "screen"
    return 0.0, ""


def best_moves(me, pool, foes, keep=()) -> list:
    """A spread, not four attacks (user 2026-11-02): its hardest hitter against
    this team, an attack that also does something (_utility) and two support
    moves that help here (_support, of two kinds when it can). Short of any of
    those, more attacks for coverage (greedy), then its own moves."""
    scores = {m: [_hit(me, f, m) for f in foes] for m in pool}
    scores = {m: v for m, v in scores.items() if max(v or [0]) > 0}
    picked, cover = [], [0.0] * len(foes)

    def reach(m):
        return sum(max(c, s) for c, s in zip(cover, scores[m]))

    def take(m):
        nonlocal cover
        cover = [max(c, s) for c, s in zip(cover, scores.pop(m))]
        picked.append(m)

    if scores:                                                  # the hitter
        take(max(scores, key=lambda x: (reach(x), sum(scores[x]))))
    util = {m: _utility(m, foes) for m in scores}
    util = {m: u for m, u in util.items() if u > 0}
    if util:                                                    # the utility attack
        take(max(util, key=lambda x: (reach(x) * (1.0 + util[x]), util[x])))
    support = {m: _support(me, foes, m) for m in sorted(pool) if m not in picked}
    kinds = []
    for _ in range(2):                                          # two support moves
        ok = {m: v * (0.6 if k in kinds else 1.0) for m, (v, k) in support.items() if v >= SUPPORT_MIN}
        if not ok:
            break
        m = max(ok, key=lambda x: (ok[x], x))
        kinds.append(support.pop(m)[1])
        picked.append(m)
    while len(picked) < 4 and scores:                           # short of any: coverage
        take(max(scores, key=lambda x: (reach(x), sum(scores[x]))))
    for m in keep:
        if len(picked) >= 4:
            break
        if _id(m) not in picked:
            picked.append(_id(m))
    return picked


# ------------------------------------------------------------------- pick --
def _leaders(gym):
    out = []
    for c in GB.build_leader_team(gym):
        src = c.source
        out.append(_Mon(getattr(src, "name", c.name), getattr(src, "type", None), c.level,
                        getattr(src, "base_stats", None), getattr(src, "iv", None),
                        getattr(src, "ev", None), c.attacks))
    return out


def shortlist(recs, foes, cap, tms=(), legend=lambda r: False):
    """[(trio records with the picked moves, score)], best first."""
    mons, rows = [], []
    for rec in recs:
        try:
            real = int(rec.get("level") or 1)
            lv = min(real, int(cap)) if cap else real
            me = _Mon(rec.get("name"), rec.get("type"), lv, rec.get("base_stats"), rec.get("iv"),
                      rec.get("ev"), [])
            me.moves = best_moves(me, move_pool(rec, lv, tms), foes, keep=rec.get("attacks") or [])
            if not me.moves:
                continue
            mons.append((rec, me))
            rows.append([_duel(me, f) for f in foes])
        except Exception:
            continue
    if len(mons) < 3:
        return []
    nf = len(foes)
    value = [sum(r) + max(r) for r in rows]
    keep = set(sorted(range(len(mons)), key=lambda i: -value[i])[:SHORTLIST])
    for f in range(nf):                            # the best answers to each opponent too
        keep |= set(sorted(range(len(mons)), key=lambda i: -rows[i][f])[:3])
    trios = []
    for t in combinations(sorted(keep), 3):
        names = {str(mons[i][0].get("name", "")).lower() for i in t}
        if len(names) < 3 or sum(1 for i in t if legend(mons[i][0])) > 1:
            continue
        score = sum(max(rows[i][f] for i in t) for f in range(nf)) + 0.5 * sum(sum(rows[i]) for i in t) / (3 * nf)
        trios.append((score, t))
    trios.sort(key=lambda x: -x[0])
    out = []
    for score, t in trios[:TRIOS]:
        lead = max(t, key=lambda i: rows[i][0])            # the best answer to their lead goes first
        order = [lead] + sorted((i for i in t if i != lead), key=lambda i: -sum(rows[i]))
        team = []
        for i in order:
            rec = copy.deepcopy(mons[i][0])
            rec["attacks"] = list(mons[i][1].moves)
            rec["_picked_moves"] = True                     # gym_battle: no scaled-moves swap
            team.append(rec)
        out.append((team, score))
    return out


def _rate(lineups, leader_sets):
    """Quick Showdown fights per lineup: [{wins, left}] or None."""
    from . import gym_showdown as GS
    from . import gym_config as CFG
    if not CFG.showdown_engine() or not GS.available():
        return None
    cmd = json.dumps({"cmd": "rate", "p2": leader_sets, "lineups": lineups,
                      "fights": FIGHTS, "hpmult": GB.HP_MULT}) + "\n"
    r = subprocess.run([str(GS.NODE), str(GS.BRIDGE)], input=cmd, capture_output=True, text=True,
                       encoding="utf-8", timeout=120, creationflags=GS.CREATE_NO_WINDOW)
    for line in (r.stdout or "").splitlines():
        out = json.loads(line)
        if out.get("ok") and isinstance(out.get("results"), list):
            return out["results"]
    return None


def _busy(parent, fn):
    """fn() in a thread behind a "Choosing your team…" box; its result."""
    box = QProgressDialog("Choosing your team…", None, 0, 0, parent)
    box.setWindowTitle("Ankimon")
    box.setWindowModality(Qt.WindowModality.WindowModal)
    box.setMinimumDuration(0)
    box.show()
    res = {}

    def run():
        try:
            res["v"] = fn()
        except Exception as e:
            res["e"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    loop = QEventLoop()
    tick = QTimer()
    tick.timeout.connect(lambda: None if t.is_alive() else loop.quit())
    tick.start(50)
    loop.exec()
    tick.stop()
    box.close()
    if "e" in res:
        raise res["e"]
    return res.get("v")


def choose(gym, cap, use_tms=False, parent=None):
    """Three saved records (copies, with this fight's moves) or None."""
    from .gym_ui import is_legendary
    from . import gym_showdown as GS
    recs = [r for r in (mw.ankimon_db.get_all_pokemon() or []) if r and r.get("name")]
    foes = _leaders(gym)
    if not foes:
        return None
    short = shortlist(recs, foes, cap, owned_tms() if use_tms else (), legend=is_legendary)
    if not short:
        return None
    best = short[0][0]
    if len(short) > 1:
        try:
            lineups = [[GS._set_from(c) for c in GB.build_player_team(team, cap)] for team, _s in short]
            leader_sets = [GS._set_from(c) for c in GB.build_leader_team(gym)]
            results = _busy(parent, lambda: _rate(lineups, leader_sets))
            if results and len(results) == len(short):
                k = max(range(len(short)), key=lambda i: (results[i].get("wins", 0), results[i].get("left", 0),
                                                          short[i][1]))
                best = short[k][0]
                _log("info", "Choose team for me: %s" % "; ".join(
                    "%s %d/%d" % ("/".join(r.get("name", "?") for r in t), res.get("wins", 0), FIGHTS)
                    for (t, _s), res in zip(short, results)))
        except Exception as e:
            _log("warning", "Choose team for me: quick fights skipped (%s)" % e)
    _log("info", "Choose team for me picked %s" % ", ".join(
        "%s (%s)" % (r.get("name"), ", ".join(r.get("attacks") or [])) for r in best))
    return best
