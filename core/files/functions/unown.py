"""unown.py - Ankimon 2.6: Unown letters (user 2026-10-27).

Every wild Unown is one of 28 letters: A-Z, ! and ?. The letter is rolled when it
appears and kept on the Pokemon as special_form ("b" ... "z", "exclamation",
"question"); an Unown caught before this has none and is an A.

  * sprite   sprites/<side>_default[_gif]/[shiny/]201-b.png ... (the sprite pack has
             all 28; get_sprite_path(..., form=...) falls back to the plain one)
  * name     "Unown B" on the HUD, in the Pokemon details, the team pickers and the
             Buddy menu (suffix())
  * catches  each letter is its own copy: a better A replaces your A, never your B
             (encounter_functions._duplicate_verdict)
  * Pokedex  each letter is its own entry, registered the first time you own it
             (table unown_registered) - collect all 28
"""
import random

UNOWN = 201
FORMS = tuple("abcdefghijklmnopqrstuvwxyz") + ("exclamation", "question")
_SIGN = {"exclamation": "!", "question": "?"}
_DDL = ("CREATE TABLE IF NOT EXISTS unown_registered ("
        "form TEXT, shiny INTEGER, first_at TEXT, PRIMARY KEY (form, shiny))")


def is_unown(species_id) -> bool:
    try:
        return int(species_id) == UNOWN
    except (TypeError, ValueError):
        return False


def roll(species_id, rng=random):
    """A letter for a newly appeared Unown; None for every other species."""
    return rng.choice(FORMS) if is_unown(species_id) else None


def _get(p, key):
    return p.get(key) if isinstance(p, dict) else getattr(p, key, None)


def form_of(p):
    """An Unown's letter ("a" when it has none, i.e. caught before letters); None
    for every other species. p is a saved record or a Pokemon object."""
    if p is None or not is_unown(_get(p, "id")):
        return None
    f = str(_get(p, "special_form") or "").lower()
    return f if f in FORMS else "a"


def letter(form) -> str:
    return _SIGN.get(form, str(form or "a").upper())


def suffix(p) -> str:
    """" B" after an Unown's name, "" for anything else."""
    f = form_of(p)
    return " " + letter(f) if f else ""


def sprite_key(species_id, form):
    """What the sprite files are named by: "201-b" for an Unown's letter, else the id
    (A is the plain 201 - the same art, and the only letter with an animated sprite)."""
    if form and form != "a" and is_unown(species_id):
        return "%d-%s" % (int(species_id), form)
    return species_id


def form_by_iid(individual_id):
    """The letter of a saved Pokemon (None if it isn't an Unown)."""
    try:
        from aqt import mw
        return form_of(mw.ankimon_db.get_pokemon(individual_id) or {})
    except Exception:
        return None


def same_letter(a, b) -> bool:
    """Catch upgrades: two copies of a species only compete if this holds."""
    return form_of(a) == form_of(b)


def registered_letters():
    """({every letter you've owned}, {letters you've owned shiny}). A letter stays
    registered after a release, like the Pokedex's species."""
    from datetime import datetime
    from aqt import mw
    db = mw.ankimon_db
    db.execute(_DDL)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    recs = list(db.get_all_pokemon() or [])
    try:
        recs += list(db.get_history() or [])
    except Exception:
        pass
    for p in recs:
        f = form_of(p) if isinstance(p, dict) else None
        if f:
            db.execute("INSERT OR IGNORE INTO unown_registered (form, shiny, first_at) VALUES (?, ?, ?)",
                       (f, 1 if p.get("shiny") else 0, now))
    try:
        db._get_connection().commit()
    except Exception:
        pass
    rows = db.execute("SELECT form, shiny FROM unown_registered").fetchall()
    return {r[0] for r in rows}, {r[0] for r in rows if r[1]}
