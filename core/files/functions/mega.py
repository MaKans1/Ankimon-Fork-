"""mega.py - daily Mega Evolution (user 2026-10-28; design: plans/mega_plan.md).

  * Once per Anki day you pick ONE Pokémon to Mega Evolve: use its Mega Stone from
    the bag (Evolution Items) while you own the Mega Bracelet. It stays a Mega until
    Anki's next day change (the rollover hour), in any number of fights, everywhere.
  * Stones are never used up. Each one matches a species (Charizardite X -> Charizard);
    the Red and Blue Orbs give Primal Groudon and Kyogre; the Dragon Key gives Mega
    Rayquaza, which must know Dragon Ascent. Zygardite isn't offered yet.
  * Today's Mega is kept in the metadata table (MEGA_KEY), never on the Pokémon's
    record, so nothing can stay a Mega by accident: a new Anki day simply ends it.
"""
import json
import math
import os
import time

BRACELET = "mega-bracelet"
DRAGON_KEY = "dragon-key"
MEGA_KEY = "mega_today"
SKIP = {"zygardemega"}          # Mega Zygarde: later (Nihil Light isn't in the move data)
_DAY = 86400

_TABLE = None
_DEX = None


def _item_id(name):
    """"Charizardite X" -> "charizardite-x" (the bag's item names)."""
    return str(name).strip().lower().replace(" ", "-").replace("'", "")


def _dex():
    global _DEX
    if _DEX is None:
        from ..resources import pokedex_path
        with open(pokedex_path, encoding="utf-8") as f:
            _DEX = json.load(f)
    return _DEX


def stones():
    """{item: {"species": dex number, "form": pokedex key, "name": "Charizard-Mega-X"}}."""
    global _TABLE
    if _TABLE is None:
        t = {}
        for key, v in _dex().items():
            if not isinstance(v, dict) or key in SKIP:
                continue
            if not str(v.get("forme", "")).startswith(("Mega", "Primal")):
                continue
            if v.get("requiredItem"):
                item = _item_id(v["requiredItem"])
            elif v.get("requiredMove") == "Dragon Ascent":
                item = DRAGON_KEY
            else:
                continue
            t[item] = {"species": int(v["species_id"]), "form": key, "name": v["name"]}
        _TABLE = t
    return _TABLE


def is_stone(item) -> bool:
    return str(item).lower() in stones()


def item_for(form) -> str:
    """The bag item that gives this form ("charizardite-x"); '' for none or the Dragon Key
    (Mega Rayquaza needs Dragon Ascent, not a held stone)."""
    for item, st in stones().items():
        if st["form"] == form:
            return "" if item == DRAGON_KEY else item
    return ""


def form_data(form):
    """The Mega's pokedex entry (types, baseStats, abilities, name), or {}."""
    return _dex().get(str(form), {}) or {}


def display_name(form) -> str:
    """"Charizard-Mega-X" -> "Mega Charizard X"; "Groudon-Primal" -> "Primal Groudon"."""
    name = str(form_data(form).get("name") or form)
    base, _, rest = name.partition("-")
    if rest.startswith("Primal"):
        return "Primal %s" % base
    extra = rest[len("Mega"):].strip("-")
    return ("Mega %s %s" % (base, extra)).strip()


def sprite_key(form) -> str:
    """The sprite files' name for a Mega form: "6-mega-x", "382-primal"."""
    d = form_data(form)
    return "%s-%s" % (d.get("species_id"), str(d.get("forme", "")).lower())


def _db():
    from ..pyobj.database_manager import get_db
    return get_db()._get_connection()


def _cutoff() -> int:
    """Epoch seconds of Anki's next day change (respects the rollover hour)."""
    from aqt import mw
    try:
        return int(mw.col.sched.day_cutoff)
    except Exception:
        try:
            hour = int(mw.col.get_config("rollover", 4) or 4)
        except Exception:
            hour = 4
        lt = time.localtime()
        today = int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hour, 0, 0, 0, 0, -1)))
        return today + _DAY if time.time() >= today else today


def today():
    """Today's Mega {"iid", "form", "item", "until"}, or None (none chosen yet today)."""
    try:
        row = _db().execute("SELECT value FROM metadata WHERE key = ?", (MEGA_KEY,)).fetchone()
        st = json.loads(row[0]) if row else None
    except Exception:
        return None
    if not st or time.time() >= float(st.get("until") or 0):
        return None
    return st


def form_for(individual_id, species_id=None):
    """The Mega form this Pokémon has today, or None. With species_id, only while it's still
    the stone's species: a Mega Floette that evolves into Florges stops being one."""
    st = today()
    if not st or not individual_id or st.get("iid") != individual_id:
        return None
    form = st.get("form")
    if species_id is not None:
        try:
            if int(species_id) != int(form_data(form).get("species_id") or 0):
                return None
        except (TypeError, ValueError):
            return None
    return form


def tooltip(item) -> str:
    """Bag tooltip for a Mega item ('' if it isn't one): the Legends: Z-A stones and the
    Dragon Key have no game text, and the classic ones' text talks about holding them."""
    item = str(item).lower()
    if item == BRACELET:
        return ("Mega Bracelet: once a day, one of your Pokémon can Mega Evolve with its Mega Stone "
                "(use the stone from the bag). Nothing to equip.")
    st = stones().get(item)
    if not st:
        return ""
    if item == DRAGON_KEY:
        return ("Dragon Key: a Rayquaza that knows Dragon Ascent becomes Mega Rayquaza until Anki's next "
                "day change (with the Mega Bracelet, one Mega a day). Never used up.")
    who = str(form_data(st["form"]).get("baseSpecies") or "")
    return ("%s: %s becomes %s until Anki's next day change (with the Mega Bracelet, one Mega a day). "
            "Never used up." % (item_name(item), who, display_name(st["form"])))


def _owned(item) -> bool:
    try:
        from aqt import mw
        it = mw.ankimon_db.get_item(item)
        return bool(it) and int((it.get("quantity") if isinstance(it, dict) else 1) or 0) > 0
    except Exception:
        return False


def has_bracelet() -> bool:
    return _owned(BRACELET)


def _knows(rec, move) -> bool:
    want = move.lower().replace(" ", "")
    return any(str(m).lower().replace(" ", "").replace("-", "") == want for m in (rec.get("attacks") or []))


def why_not(rec, item) -> str:
    """'' if this Pokémon can Mega Evolve with this item right now, else the reason."""
    st = stones().get(str(item).lower())
    if not st:
        return "Not a Mega Stone."
    if int(rec.get("id") or 0) != st["species"]:
        return "Doesn't match this stone."
    if item == DRAGON_KEY and not _knows(rec, "Dragon Ascent"):
        return "Needs to know Dragon Ascent"
    return ""


def evolve(rec, item):
    """Make this Pokémon today's Mega. Returns (ok, message)."""
    if not has_bracelet():
        return False, "You need the Mega Bracelet to Mega Evolve."
    st = today()
    if st:
        return False, ("%s is already today's Mega. Another Pokémon can Mega Evolve after "
                       "Anki's next day change." % display_name(st.get("form")))
    why = why_not(rec, item)
    if why:
        return False, why
    form = stones()[str(item).lower()]["form"]
    state = {"iid": rec.get("individual_id"), "form": form, "item": str(item).lower(), "until": _cutoff()}
    try:
        con = _db()
        con.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (MEGA_KEY, json.dumps(state)))
        con.commit()
    except Exception as e:
        return False, "Couldn't save the Mega Evolution: %s" % e
    who = rec.get("nickname") or str(rec.get("name") or "").title()
    return True, "%s Mega Evolved into %s! It stays a Mega until Anki's next day change." % (who, display_name(form))


def engine(engine_mon, pobj, level=None):
    """Today's Mega as the battle engine sees it: the Mega's base stats, types and
    ability at `level` (default: its own), HP rescaled into that level's pool (the
    Pokémon keeps its real HP; wild_rules.real_hp converts back). Megas never change
    base HP, so at its own level the HP pool is the same."""
    form = form_for(getattr(pobj, "individual_id", None), getattr(pobj, "id", None))
    d = form_data(form) if form else {}
    if not d:
        return engine_mon
    from ..poke_engine.helpers import normalize_name
    P = type(pobj)
    lv = int(level or pobj.level)
    iv, ev, bs = pobj.iv or {}, pobj.ev or {}, d.get("baseStats") or {}
    nat = getattr(pobj, "nature", "serious")

    def st(k):
        return P.calc_stat(k, int(bs.get(k, 50)), lv, int(iv.get(k, 0)), int(ev.get(k, 0)), nat)
    mx, rmax, rhp = max(1, st("hp")), max(1, int(pobj.max_hp)), int(pobj.hp)
    engine_mon.level = lv
    engine_mon.attack, engine_mon.defense = st("atk"), st("def")
    engine_mon.special_attack, engine_mon.special_defense = st("spa"), st("spd")
    engine_mon.speed = st("spe")
    engine_mon.maxhp = mx
    engine_mon.hp = 0 if rhp <= 0 else (mx if rhp >= rmax else max(1, round(rhp * mx / rmax)))
    types = [normalize_name(t) for t in d.get("types") or []]
    if types:
        engine_mon.types = types
    ab = (d.get("abilities") or {}).get("0")
    if ab:
        engine_mon.ability = normalize_name(ab)
    return engine_mon


def sprite_path(pobj, side, sprite_type):
    """Today's Mega's sprite - or a rematched leader's (pobj.mega_form) - shiny if it has
    one, or None. A missing back sprite falls back to the front one (the HUD mirrors yours)."""
    form = getattr(pobj, "mega_form", None) or form_for(getattr(pobj, "individual_id", None), getattr(pobj, "id", None))
    if not form:
        return None
    from .sprite_functions import get_sprite_path, SUBSTITUTE_PATH
    key = sprite_key(form)
    for shiny in ((True, False) if getattr(pobj, "shiny", False) else (False,)):
        p = get_sprite_path(side, sprite_type, key, shiny, getattr(pobj, "gender", None))
        if p and p != SUBSTITUTE_PATH:
            return p
    return None


# ------------------------------------------------------------ getting them --
# (chunk 4) The Mega Bracelet + a starter with its stone (Korrina in Kalos / Norman in
# Hoenn, whichever first; past it already: the next gym win there), rare wild finds in
# Kalos/Hoenn, Kalos/Hoenn rematch loot once that region's Elite Four is beaten, and the
# legendary stones from every region's Champion (one guaranteed per Champion).
MILESTONE = {"Kalos": 603, "Hoenn": 305}
STARTERS = {"Kalos": [("Chespin", "chesnaughtite"), ("Fennekin", "delphoxite"), ("Froakie", "greninjite")],
            "Hoenn": [("Treecko", "sceptilite"), ("Torchic", "blazikenite"), ("Mudkip", "swampertite")]}
STARTER_LEVEL = 5
LEGENDARY = ("mewtwonite-x", "mewtwonite-y", "latiasite", "latiosite", "diancite", "red-orb", "blue-orb")
WILD_DROP_CHANCE = 0.25         # of item finds in Kalos/Hoenn, once you have the bracelet
REMATCH_STONE_CHANCE = 0.30     # Kalos/Hoenn rematch wins after that region's Elite Four
CHAMPION_STONE_CHANCE = 0.20    # Champion rematches, after the guaranteed one
PICK_KEY = "mega_pick_pending"          # metadata: region whose starter pick is still owed
GUARANTEE_KEY = "mega_champion_given"   # metadata: Champions that gave their guaranteed stone
RAYQUAZA_KEY = "mega_rayquaza_done"     # metadata: Dragon Ascent taught, Dragon Key given
RAYQUAZA = 384


def _get_meta(key, default=None):
    try:
        row = _db().execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default
    except Exception:
        return default


def _set_meta(key, value):
    con = _db()
    if value is None:
        con.execute("DELETE FROM metadata WHERE key = ?", (key,))
    else:
        con.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, str(value)))
    con.commit()


def item_name(item) -> str:
    return str(item).replace("-", " ").title()


def regular_pool():
    """Mega Stones you don't own yet, legendary ones and the Dragon Key aside."""
    return [i for i in stones() if i not in LEGENDARY and i != DRAGON_KEY and not _owned(i)]


def _region():
    try:
        from ..wild import wild_rules
        return wild_rules.region()
    except Exception:
        return None


def wild_drop(rng=None):
    """utils.random_item: in Kalos/Hoenn with the bracelet, a quarter of item finds are a
    Mega Stone you don't have yet. Returns that stone (the caller gives it), or None."""
    import random
    rng = rng or random
    if _region() not in MILESTONE or not has_bracelet() or rng.random() >= WILD_DROP_CHANCE:
        return None
    pool = regular_pool()
    if not pool:
        return None
    check_rayquaza_later()
    return rng.choice(pool)


def _give(item):
    from ..utils import give_item
    give_item(item)


def _themed_stone(type_theme, rng):
    """A stone you don't own whose Mega shares the leader's type, else any you don't own."""
    pool = regular_pool()
    themed = [i for i in pool if str(type_theme).title() in (form_data(stones()[i]["form"]).get("types") or [])]
    return rng.choice(themed or pool) if pool else None


def gym_rewards(gym, defeated, rng=None):
    """gym_battle.award_victory: (notes, loot names) for the Mega rewards of this win."""
    import random
    rng = rng or random
    notes, loot = [], []
    if getattr(gym, "is_test", False):
        return notes, loot
    try:
        from ..gym import gym_data
    except ImportError:                         # gyms package off: no gym rewards
        return notes, loot
    region = str(getattr(gym, "region", "") or "")
    gid = int(getattr(gym, "gym_id", 0) or 0)
    kind = getattr(gym, "kind", "")
    done = set(int(x) for x in (defeated or ())) | {gid}
    ms = MILESTONE.get(region)
    if ms and ms in done and not has_bracelet() and kind in (gym_data.GYM, gym_data.ELITE4, gym_data.CHAMPION):
        _give(BRACELET)
        _set_meta(PICK_KEY, region)
        loot.append("Mega Bracelet")
        notes.append("You received the Mega Bracelet! Once a day, one of your Pokémon can Mega Evolve "
                     "(use its Mega Stone from the bag). Next, choose a partner to raise.")
        _later(show_pick)
    if not has_bracelet():
        return notes, loot
    if getattr(gym, "is_rematch", False) and ms:
        elite = {g.gym_id for g in gym_data.ladder(region) if g.kind == gym_data.ELITE4}
        if elite and elite <= done and rng.random() < REMATCH_STONE_CHANCE:
            s = _themed_stone(getattr(gym, "type_theme", ""), rng)
            if s:
                _give(s)
                loot.append(item_name(s))
    if kind == gym_data.CHAMPION:
        pool = [i for i in LEGENDARY if not _owned(i)]
        given = set(json.loads(_get_meta(GUARANTEE_KEY) or "[]"))
        pick = None
        if pool and gid not in given:
            pick = rng.choice(pool)
            given.add(gid)
            _set_meta(GUARANTEE_KEY, json.dumps(sorted(given)))
        elif pool and getattr(gym, "is_rematch", False) and rng.random() < CHAMPION_STONE_CHANCE:
            pick = rng.choice(pool)
        if pick:
            _give(pick)
            loot.append(item_name(pick))
    if loot:
        check_rayquaza_later()
    return notes, loot


def _later(fn, ms=1200):
    try:
        from aqt.qt import QTimer
        QTimer.singleShot(ms, fn)
    except Exception:
        pass


def _sprite(key):
    from ..resources import pkmnimgfolder
    return os.path.join(str(pkmnimgfolder), "front_default", "%s.png" % key)


_OPEN = set()       # the pick / Rayquaza dialogs on screen now


def show_pick():
    """The starter pick that comes with the bracelet: one of the region's three starters
    (Lv 5) with the Mega Stone for its final form. Closing it keeps it owed (next start)."""
    # Qt keeps running timers while a dialog waits, so a second call (startup + a gym win)
    # could open a second pick on top of the first - and grant a second starter
    region = _get_meta(PICK_KEY)
    if region not in STARTERS or "pick" in _OPEN:
        return
    _OPEN.add("pick")
    try:
        _show_pick(region)
    finally:
        _OPEN.discard("pick")


def _show_pick(region):
    from aqt import mw
    from aqt.qt import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPixmap, Qt
    dlg = QDialog(mw)
    dlg.setWindowTitle("Mega Evolution - choose a partner")
    lay = QVBoxLayout(dlg)
    head = QLabel("<b>Choose a partner to raise.</b><br>It comes with the Mega Stone for its final form: "
                  "once it's fully evolved, it can Mega Evolve.")
    head.setWordWrap(True)
    lay.addWidget(head)
    row = QHBoxLayout()
    chosen = []
    for name, stone in STARTERS[region]:
        col = QVBoxLayout()
        pic = QLabel()
        sid = stones()[stone]["species"]
        pic.setPixmap(QPixmap(_sprite(sid)).scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                                                   Qt.TransformationMode.FastTransformation))
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn = QPushButton("%s\n+ %s" % (name, item_name(stone)))
        btn.setToolTip("Grows into %s, which becomes %s."
                       % (str(form_data(stones()[stone]["form"]).get("baseSpecies") or ""),
                          display_name(stones()[stone]["form"])))
        btn.clicked.connect(lambda _=False, n=name, s=stone: (chosen.append((n, s)), dlg.accept()))
        col.addWidget(pic)
        col.addWidget(btn)
        row.addLayout(col)
    lay.addLayout(row)
    dlg.exec()
    if chosen:
        _grant_pick(region, *chosen[0])


def _grant_pick(region, name, stone):
    from aqt.utils import showInfo
    if _get_meta(PICK_KEY) != region:           # no longer owed (already picked)
        return
    try:
        import random
        from ..gym.gym_data import GymMon
        from ..gym.gym_battle import build_leader_pokemon, _dn
        from ..gym import legends
        from .pokemon_functions import shiny_chance, pick_random_gender
        from .encounter_functions import save_caught_pokemon
        from ..singletons import achievements
        p = build_leader_pokemon(GymMon(name, STARTER_LEVEL, None))
        if p is None:
            raise ValueError("couldn't build %s" % name)
        p.iv = {k: random.randint(legends.IV_FLOOR, 31) for k in ("hp", "atk", "def", "spa", "spd", "spe")}
        mx = int(p.calculate_max_hp())
        p.max_hp = p.hp = p.current_hp = mx
        try:
            p.shiny = bool(shiny_chance())
        except Exception:
            p.shiny = False
        try:
            p.gender = pick_random_gender(name.lower())
        except Exception:
            pass
        save_caught_pokemon(p, _dn(p.name), achievements, keep_duplicate=True)   # a gift: never released / swapped
        if not _owned(stone):
            _give(stone)
        _set_meta(PICK_KEY, None)
    except Exception as e:
        showInfo("Couldn't add your partner (%s). You'll be asked again next time Anki starts." % e)
        return
    showInfo("%s joined you, with the %s! Once it's fully evolved, it can Mega Evolve into %s."
             % (name, item_name(stone), display_name(stones()[stone]["form"])), title="Mega Evolution")
    check_rayquaza_later()


# --------------------------------------------------------------- Rayquaza --
# (chunk 5) Rayquaza no longer starts with Dragon Ascent (the installer takes it out of its
# learnset). Owning every other Mega Stone + a Rayquaza: a one-button scene teaches it
# (forget a move if it knows four), then the Dragon Key goes into the bag.
def _all_stones() -> bool:
    return all(_owned(i) for i in stones() if i != DRAGON_KEY)


def _rayquaza():
    """Your Rayquaza to teach: the buddy if it's one, else the highest level. None if none."""
    try:
        from aqt import mw
        rows = [r for r in (mw.ankimon_db.get_all_pokemon() or []) if r and int(r.get("id") or 0) == RAYQUAZA]
    except Exception:
        return None
    if not rows:
        return None
    try:
        from ..singletons import main_pokemon
        buddy = getattr(main_pokemon, "individual_id", None)
    except Exception:
        buddy = None
    return next((r for r in rows if r.get("individual_id") == buddy), None) or max(rows, key=lambda r: int(r.get("level") or 1))


def check_rayquaza_later():
    _later(check_rayquaza, 1500)


def check_rayquaza():
    """Every other Mega Stone + a Rayquaza: the Dragon Ascent scene (once). Waits otherwise."""
    if "rayquaza" in _OPEN or _get_meta(RAYQUAZA_KEY) or not _all_stones():
        return                                  # (_OPEN: see show_pick)
    rec = _rayquaza()
    if rec:
        _OPEN.add("rayquaza")
        try:
            _rayquaza_scene(rec)
        finally:
            _OPEN.discard("rayquaza")


def _reload(rec):
    """The Pokémon's record as saved now (the scene can sit on screen a while)."""
    try:
        from aqt import mw
        iid = rec.get("individual_id")
        return next((r for r in (mw.ankimon_db.get_all_pokemon() or [])
                     if r and r.get("individual_id") == iid), rec)
    except Exception:
        return rec


def _rayquaza_scene(rec):
    from aqt import mw
    from aqt.qt import QDialog, QVBoxLayout, QLabel, QPushButton, QPixmap, Qt
    n = sum(1 for i in stones() if i != DRAGON_KEY)

    class Scene(QDialog):
        def reject(self):                       # no way out but learning it
            pass
    dlg = Scene(mw)
    dlg.setWindowTitle("Mega Rayquaza")
    dlg.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
    dlg.setStyleSheet("QDialog {background:#0b1d3a; border:2px solid #85b7eb;}")
    lay = QVBoxLayout(dlg)
    pic = QLabel()
    pm = QPixmap(_sprite(sprite_key("rayquazamega")))
    pic.setPixmap(pm.scaled(pm.width() * 2, pm.height() * 2, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.FastTransformation))
    pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(pic)
    who = rec.get("nickname") or "Rayquaza"
    box = QLabel("The %d Mega Stones glow as one...<br>A roar splits the clouds!<br>"
                 "<span style='color:#1d7a4f;font-weight:bold'>%s</span> wants to learn "
                 "<span style='color:#b8860b;font-weight:bold'>Dragon Ascent</span>!" % (n, who))
    box.setTextFormat(Qt.TextFormat.RichText)
    box.setWordWrap(True)
    box.setStyleSheet("background:#f8f8f0; color:#222; border:3px solid #444; border-radius:8px; "
                      "padding:10px 12px; font-family:monospace; font-size:14px;")
    lay.addWidget(box)
    btn = QPushButton("Learn: Dragon Ascent")
    btn.setStyleSheet("background:#85b7eb; color:#042c53; padding:6px 14px; border-radius:6px; font-weight:bold;")
    btn.clicked.connect(dlg.accept)
    lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)
    dlg.exec()
    _teach_dragon_ascent(_reload(rec))


def _teach_dragon_ascent(rec):
    from aqt import mw
    from aqt.utils import showInfo
    moves = [m for m in (rec.get("attacks") or []) if m]
    if not _knows(rec, "Dragon Ascent"):
        if len(moves) >= 4:
            drop = _forget_one(moves)
            moves = [m for m in moves if m != drop]
        moves.append("Dragon Ascent")
        rec["attacks"] = moves
        mw.ankimon_db.save_pokemon(rec)
        try:                                    # the buddy in memory too, or it saves the old moves back
            from ..singletons import main_pokemon
            if getattr(main_pokemon, "individual_id", None) == rec.get("individual_id"):
                from .update_main_pokemon import update_main_pokemon
                update_main_pokemon(main_pokemon)
        except Exception:
            pass
    if not _owned(DRAGON_KEY):
        _give(DRAGON_KEY)
    _set_meta(RAYQUAZA_KEY, "1")
    showInfo("%s learned Dragon Ascent!\n\nThe Dragon Key is in your bag (Evolution Items): use it to "
             "Mega Evolve Rayquaza." % (rec.get("nickname") or "Rayquaza"), title="Mega Rayquaza")


def _forget_one(moves):
    """Pick the move Dragon Ascent replaces. Required: there's no cancel."""
    from aqt import mw
    from aqt.qt import QDialog, QVBoxLayout, QLabel, QPushButton

    class Forget(QDialog):
        def reject(self):
            pass
    dlg = Forget(mw)
    dlg.setWindowTitle("Dragon Ascent")
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel("Rayquaza already knows four moves. Forget which one for Dragon Ascent?"))
    picked = []
    for m in moves:
        b = QPushButton("Forget %s" % m)
        b.clicked.connect(lambda _=False, mv=m: (picked.append(mv), dlg.accept()))
        lay.addWidget(b)
    dlg.exec()
    return picked[0] if picked else moves[-1]


def on_startup():
    """After Anki starts: a starter pick still owed, or Mega Rayquaza waiting."""
    if _get_meta(PICK_KEY) in STARTERS:
        _later(show_pick, 2500)
    _later(check_rayquaza, 4000)


def wild_level(real_level, mean, sd, alpha_z):
    """The level a Mega fights at in wild battles under a region's cap: above the
    curve's middle (1.5 SD), below where Alphas start, never above its real level."""
    lv = min(int(round(mean + 1.5 * sd)), int(math.floor(mean + alpha_z * sd)) - 1)
    return max(1, min(int(real_level), max(int(round(mean)), lv)))
