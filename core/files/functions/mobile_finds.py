"""
mobile_finds.py - what you'd have met while reviewing on your phone (user 2026-11-05).

A sync that brings in cards answered somewhere else (AnkiMobile, AnkiDroid,
AnkiWeb) turns them into the wild encounters they'd have been here - cards per
encounter is measured from your own desktop play - and rolls each one the way
a desktop encounter is rolled:
  * the shiny odds: each hit gives you a shiny non-legendary Pokemon from your
    current region at its wild level, with a popup showing its sprite ("While
    adventuring on mobile, you encountered this shiny X!"). It's kept by the
    usual duplicate rules, like a catch.
  * the legendary odds (gym/legends.py): each hit brings the usual battle offer,
    opening "While exploring on mobile, ...". Several line up one after another
    (each Pokemon at most once per sync).
Shinies come first, then the legendary offers. Battles, XP and training points
from phone cards stay desktop-only.

Only reviews done after this was installed count (a full download of an old
collection on a new computer brings nothing). State lives in
user_files/mobile_finds.json: desktop cards and encounters (the ratio), phone
cards not rolled yet, the part-encounter carried over, and shinies found but
not shown yet - so a sync as Anki closes is rolled at the next start.
"""
import json
import os
import random
import time
import uuid

DEFAULT_RATIO = 3.3          # cards per desktop encounter until enough are measured (Oct-Nov 2026 average)
MIN_ENCOUNTERS = 30          # desktop encounters before the measured ratio is used
RATIO_RANGE = (1.0, 15.0)
DECAY_AT = 3000              # past this many desktop cards both counts halve: recent play counts most
SHINY_TIERS = ("Normal", "Baby")    # no legendaries, mythicals or Ultra Beasts
_REVIEWS = "SELECT count() FROM revlog WHERE type IN (0, 1, 2, 3) AND id >= ?"

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_files", "mobile_finds.json")
_state = None
_before = None               # review count when the sync started
_cards = 0                   # desktop cards since the last encounter
_busy = False
_set_up = False
_closing = False            # Anki is closing: leave it for the next start


def _log(level, msg):
    try:
        from ..singletons import logger
        logger.log(level, "mobile finds: %s" % msg)
    except Exception:
        print("Ankimon mobile finds:", msg)


# ---------------------------------------------------------------- state --
def _load() -> dict:
    global _state
    if _state is None:
        try:
            with open(_PATH, encoding="utf-8") as f:
                _state = json.load(f)
        except Exception:
            _state = {}
        if not _state.get("since"):
            _state["since"] = int(time.time())       # reviews before this never count
            _save()
    return _state


def _save():
    try:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        tmp = _PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state or {}, f, indent=1)
        os.replace(tmp, _PATH)
    except Exception as e:
        _log("error", "could not save: %s" % e)


def ratio() -> float:
    """Cards per wild encounter on this desktop."""
    st = _load()
    enc, cards = float(st.get("desk_encounters") or 0), float(st.get("desk_cards") or 0)
    if enc < MIN_ENCOUNTERS or cards <= 0:
        return DEFAULT_RATIO
    return max(RATIO_RANGE[0], min(RATIO_RANGE[1], cards / enc))


def note_card(*_args):
    """Once per card answered here (reviewer_did_answer_card)."""
    global _cards
    _cards += 1


def note_encounter():
    """Once per new desktop wild encounter (encounter_functions.new_pokemon)."""
    global _cards
    st = _load()
    st["desk_cards"] = float(st.get("desk_cards") or 0) + _cards
    st["desk_encounters"] = float(st.get("desk_encounters") or 0) + 1
    _cards = 0
    if st["desk_cards"] > DECAY_AT:
        st["desk_cards"] /= 2.0
        st["desk_encounters"] /= 2.0
    _save()


# ----------------------------------------------------------------- sync --
def _count():
    from aqt import mw
    return int(mw.col.db.scalar(_REVIEWS, int(_load()["since"]) * 1000) or 0)


def _on_sync_start():
    global _before
    try:
        _before = _count()
    except Exception:
        _before = None


def _on_sync_done():
    global _before
    b, _before = _before, None
    try:
        got = _count() - b if b is not None else 0
    except Exception:
        got = 0
    if got > 0:
        st = _load()
        st["phone_cards"] = int(st.get("phone_cards") or 0) + got
        _save()
        _log("info", "%d reviews came in with the sync" % got)
    _later(2500)


def _later(ms):
    try:
        from aqt.qt import QTimer
        QTimer.singleShot(int(ms), process)
    except Exception:
        pass


# ---------------------------------------------------------------- rolls --
def _boost() -> int:
    try:
        from ..wild import wild_rules
        return int(wild_rules.goal_bonus())
    except Exception:
        return 1


def _ready() -> bool:
    """Main window up, no other dialog, no gym battle running."""
    from aqt import mw
    from aqt.qt import QApplication
    if mw is None or getattr(mw, "col", None) is None:
        return False
    if QApplication.activeModalWidget() is not None:
        return False
    try:
        from ..gym import gym_ui
        if gym_ui.gym_is_active():
            return False
    except Exception:
        pass
    return True


def process():
    """Roll the phone cards waiting, then show what turned up."""
    global _busy
    if _busy or _closing:
        return
    st = _load()
    if not int(st.get("phone_cards") or 0) and not int(st.get("shinies") or 0):
        return
    try:
        if not _ready():
            _later(5000)
            return
    except Exception:
        return
    _busy = True
    try:
        found = []
        cards = int(st.get("phone_cards") or 0)
        if cards > 0:
            from .pokemon_functions import shiny_chance
            total = cards / ratio() + float(st.get("carry") or 0)
            n = int(total)
            b = _boost()
            hits = sum(1 for _ in range(n) if shiny_chance(b))
            try:
                from ..gym import legends
                found = legends.roll_many(n)
            except Exception:
                found = []
            st["phone_cards"] = 0
            st["carry"] = round(total - n, 4)
            st["shinies"] = int(st.get("shinies") or 0) + hits
            _save()
            _log("info", "%d phone cards = %d encounters: %d shiny, %d legendary"
                 % (cards, n, hits, len(found)))
        while int(st.get("shinies") or 0) > 0 and not _closing:
            p, note = _give_shiny()             # raises if it couldn't be saved: kept for later
            st["shinies"] = int(st.get("shinies") or 0) - 1
            _save()
            if p is not None:
                _popup(p, note)
        if found:
            try:
                from ..gym import legends     # found is only non-empty with the gyms package
                legends.queue(found)
            except ImportError:
                pass
    except Exception as e:
        _log("error", "failed: %s" % e)
    finally:
        _busy = False


# --------------------------------------------------------------- shinies --
def _level(buddy):
    """The region's wild level (and the evolution stage it implies), as a spawn here."""
    try:
        from ..wild import wild_rules as W
        keep = (getattr(W.STATE, "alpha", False), getattr(W.STATE, "z", None))
        try:
            lv = W.pick_level(buddy)
            z = W.STATE.z
        finally:
            W.STATE.alpha, W.STATE.z = keep
        if lv:
            return int(lv), z
    except Exception:
        pass
    return max(1, int(buddy) + random.randint(-3, 3)), None


def _species(level, z):
    from . import encounter_functions as EF
    from .pokedex_functions import search_pokedex_by_id
    try:
        reviews = EF.ankimon_tracker_obj.get_total_reviews()
        tlevel = EF.trainer_card.level
    except Exception:
        reviews, tlevel = 0, 1
    for _ in range(400):
        try:
            tier = EF.get_tier(reviews, tlevel)
        except Exception:
            tier = "Normal"
        if tier not in SHINY_TIERS:
            continue
        sid = EF.get_random_pokemon_in_tier(tier)
        name = search_pokedex_by_id(sid)
        if not EF.check_id_ok(sid) or level < EF.check_min_generate_level(str(name).lower()):
            continue
        if z is not None:                   # evolution stage from where the level fell on the curve
            try:
                from ..wild import wild_rules as W
                old = W.STATE.z
                W.STATE.z = z
                try:
                    st = W.stage_for(sid, level)
                finally:
                    W.STATE.z = old
                if st and st != sid:
                    sid = st
            except Exception:
                pass
        return int(sid), tier
    return None, None


def _give_shiny():
    """A shiny from the current region joins you: (PokemonObject, duplicate note), or
    (None, "") when no species fits. Raises if it couldn't be saved."""
    from . import encounter_functions as EF
    from .pokedex_functions import search_pokedex_by_id
    from ..pyobj.pokemon_obj import PokemonObject
    from ..singletons import main_pokemon, achievements
    level, z = _level(getattr(main_pokemon, "level", 5) or 5)
    sid, tier = _species(level, z)
    if sid is None:
        _log("warning", "no species for a shiny here")
        return None, ""
    name = search_pokedex_by_id(sid)
    moves = EF.get_all_pokemon_moves(name, level) or ["Tackle"]
    if len(moves) > 4:
        moves = random.sample(moves, 4)
    ability = "no_ability"
    abil = EF.search_pokedex(name, "abilities")
    if isinstance(abil, dict):
        nums = [v for k, v in abil.items() if str(k).isdigit()]
        if nums:
            ability = random.choice(nums)
    try:
        from .unown import roll as unown_roll
        letter = unown_roll(sid)
    except Exception:
        letter = None
    actual = EF.search_pokedex(name, "actual_id")
    p = PokemonObject(
        type=EF.search_pokedex(name, "types"), name=EF.display_name(name), id=sid, shiny=True,
        level=level, ability=ability, gender=EF.pick_random_gender(name),
        growth_rate=EF.get_growth_rate(sid), captured_date=None, tier=tier,
        individual_id=str(uuid.uuid4()), base_stats=EF.search_pokedex(name, "baseStats"),
        attacks=moves, base_experience=EF.get_base_experience(actual),
        iv={k: random.randint(0, 31) for k in ("hp", "atk", "def", "spa", "spd", "spe")},
        ev_yield=EF.get_effort_values(actual), special_form=letter)
    hp = p.calculate_max_hp()
    p.hp = p.current_hp = p.max_hp = hp
    EF.save_caught_pokemon(p, None, achievements)
    note = EF._DUP_NOTE[0] if hasattr(EF, "_DUP_NOTE") else ""
    _log("info", "shiny %s Lv %d from phone reviews (%s)" % (p.name, level, note or "kept"))
    return p, note


def _popup(p, note):
    from aqt import mw
    from aqt.qt import QDialog, QVBoxLayout, QLabel, QPushButton, QPixmap, QMovie, QSize, Qt
    from .sprite_functions import get_sprite_path
    d = QDialog(mw)
    d.setWindowTitle("Ankimon")
    lay = QVBoxLayout(d)
    lay.setContentsMargins(24, 18, 24, 16)
    lay.setSpacing(10)
    head = QLabel("While adventuring on mobile, you encountered this shiny %s!" % p.name)
    head.setWordWrap(True)
    head.setAlignment(Qt.AlignmentFlag.AlignCenter)
    head.setStyleSheet("font-size: 15px; font-weight: bold;")
    lay.addWidget(head)
    pic = QLabel()
    pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
    pic.setMinimumSize(160, 160)
    movie = None
    form = getattr(p, "special_form", None)
    try:
        path = get_sprite_path("front", "gif", p.id, True, p.gender, form)
        if path and str(path).lower().endswith(".gif"):
            movie = QMovie(str(path))
            movie.setScaledSize(QSize(160, 160))
            pic.setMovie(movie)
            movie.start()
        else:
            path = path or get_sprite_path("front", "png", p.id, True, p.gender, form)
            pm = QPixmap(str(path))
            if not pm.isNull():
                pic.setPixmap(pm.scaled(160, 160, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.FastTransformation))
    except Exception as e:
        _log("warning", "sprite: %s" % e)
    lay.addWidget(pic)
    sub = QLabel("✨ Shiny %s, Lv %d ✨" % (p.name, int(p.level)))
    sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
    sub.setStyleSheet("color: #DAA520; font-size: 14px; font-weight: bold;")
    lay.addWidget(sub)
    msg = QLabel(note or "It joined your Pokémon.")
    msg.setWordWrap(True)
    msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(msg)
    ok = QPushButton("Nice!")
    ok.setDefault(True)
    ok.clicked.connect(d.accept)
    lay.addWidget(ok, 0, Qt.AlignmentFlag.AlignCenter)
    d.setMinimumWidth(340)
    try:
        d.exec()
    finally:
        if movie is not None:           # let go of the file (Windows locks it; update guard)
            movie.stop()
            movie.setFileName("")


# ---------------------------------------------------------------- setup --
def setup():
    global _set_up
    if _set_up:
        return
    _set_up = True
    from aqt import gui_hooks
    gui_hooks.reviewer_did_answer_card.append(note_card)
    gui_hooks.sync_will_start.append(_on_sync_start)
    gui_hooks.sync_did_finish.append(_on_sync_done)
    gui_hooks.profile_did_open.append(_opened)
    gui_hooks.profile_will_close.append(_closed)
    _load()                                   # first run: reviews from now on count
    _later(15000)


def _opened():
    global _closing
    _closing = False
    _later(8000)                              # finds from a sync as Anki closed last time


def _closed():
    global _closing
    _closing = True
