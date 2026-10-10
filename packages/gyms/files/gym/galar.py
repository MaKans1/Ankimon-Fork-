"""
galar.py - Galar's Sword / Shield gyms.

  * Two Galar slots have a different leader per version: Bea (Fighting) or
    Allister (Ghost), Gordie (Rock) or Melony (Ice) - and the Champion Cup's
    Bea / Allister. The first time you arrive in Galar a popup asks which;
    the choice is kept (gym_meta "version:Galar").
  * The ladder then shows your version's leaders (gym_data.ladder); the other
    version's leader is available in Gym Rematches once you've cleared that
    slot (rematch.beaten_here).
  * Close the popup without choosing and Sword is used until you choose
    (it asks again on your next trip to Galar).
  * Kubfu: joins after Milo; then rare in Galar's wild (see below).
"""
from .gym_data import full_ladder, VERSIONS, _VERSION

REGION = "Galar"
META = "version:Galar"


def _progress():
    from .gym_ui import progress
    return progress()


def chosen():
    try:
        return _progress().get_meta(META) or None
    except Exception:
        return None


def choose(version) -> None:
    _progress().set_meta(META, version)
    _VERSION[REGION] = version


def _has_versions() -> bool:
    return any(g.version for g in full_ladder(REGION))


def ask(parent=None) -> bool:
    """The Sword / Shield popup. True if a version was picked."""
    from aqt import mw
    from aqt.qt import QDialog, QVBoxLayout, QLabel, QPushButton
    lad = full_ladder(REGION)
    by = {v: [g for g in lad if g.version == v] for v in VERSIONS[REGION]}
    dlg = QDialog(parent or mw)
    dlg.setWindowTitle("Galar")
    v = QVBoxLayout(dlg)
    lab = QLabel("<b>Welcome to Galar!</b> Which gym challenge are you taking on?")
    lab.setWordWrap(True)
    v.addWidget(lab)
    picked = {}
    for ver in VERSIONS[REGION]:
        gyms = sorted({(g.leader, g.type_theme) for g in by[ver]}, key=lambda x: x[0])
        b = QPushButton("%s - %s" % (ver.capitalize(), ", ".join("%s (%s)" % lt for lt in gyms)))
        b.setStyleSheet("text-align:left; padding:6px 10px;")
        b.clicked.connect(lambda _c=False, x=ver: (picked.update(v=x), dlg.accept()))
        v.addWidget(b)
    later = QPushButton("Decide later")
    later.clicked.connect(dlg.reject)
    v.addWidget(later)
    dlg.exec()
    if not picked.get("v"):
        return False
    choose(picked["v"])
    try:
        from aqt.utils import tooltip
        tooltip("%s it is!" % picked["v"].capitalize())
    except Exception:
        pass
    return True


def on_enter():
    """Travelled to Galar: ask once (until a version is chosen)."""
    if _has_versions() and not chosen():
        ask()


# --------------------------------------------------------------- Kubfu --
# Sw/Sh (Isle of Armor) gives Kubfu at Lv 10, so it joins after Milo, Galar's
# first gym. After that it's also in Galar's wild (it can be found again and
# again), four times as often as Mewtwo and twice as likely to be shiny. The
# towers (Expeditions) evolve one: gym/expedition.py, evolves=.
KUBFU = 891
KUBFU_LEVEL = 10
KUBFU_AFTER = 801             # Milo
KUBFU_RATE = 4 / 750.0        # wild_rules.special_spawn (Mewtwo: 1/750)
KUBFU_SHINY = 2               # wild_rules.shiny_boost
JOINED = "kubfu_joined"


def kubfu_joined() -> bool:
    try:
        return bool(_progress().get_meta(JOINED))
    except Exception:
        return False


def kubfu_gift(gym) -> str:
    """After Milo's first win: a Kubfu joins you (once). Recap note, or ''."""
    if int(getattr(gym, "gym_id", 0) or 0) != KUBFU_AFTER or kubfu_joined():
        return ""
    try:
        import random
        from .gym_data import GymMon
        from .gym_battle import build_leader_pokemon, _dn
        from . import legends
        from ..functions.pokemon_functions import shiny_chance, pick_random_gender
        from ..functions.encounter_functions import save_caught_pokemon
        from ..singletons import achievements
        p = build_leader_pokemon(GymMon("Kubfu", KUBFU_LEVEL, None))
        if p is None:
            return ""
        p.iv = {k: random.randint(legends.IV_FLOOR, 31) for k in ("hp", "atk", "def", "spa", "spd", "spe")}
        mx = int(p.calculate_max_hp())
        p.max_hp = p.hp = p.current_hp = mx
        p.shiny = bool(shiny_chance(KUBFU_SHINY))
        p.tier = "Legendary"
        try:
            p.gender = pick_random_gender("kubfu")
        except Exception:
            pass
        save_caught_pokemon(p, _dn(p.name), achievements)
        _progress().set_meta(JOINED, "1")
    except Exception as e:
        print("Ankimon Kubfu gift:", e)
        return ""
    return ("A Kubfu was watching your battle - it's taken a liking to you and joined you!%s "
            "Once you have 4 Galar badges, the Tower of Darkness or the Tower of Waters "
            "(Expeditions) can train it." % (" And it's SHINY!" if p.shiny else ""))
