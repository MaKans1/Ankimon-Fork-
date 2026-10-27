"""
details_info.py - Ankimon 2.5: info lines for the Pokemon details window.

  * evolution_hint(): what it takes to evolve, shown where "Evolve now" would
    appear - a level, a stone or other item, friendship, the no-trade rule
    (Lv 37 + friendship), Kubfu's towers. Methods Ankimon can't do yet (level
    up knowing a move / holding an item / special conditions) say so.
  * ability_desc(): a short description for the Ability tooltip, from
    data_files/ability_text.json (Pokemon Showdown's ability text, MIT).
"""
import json
import os
import re

_ADDON = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_abilities = None

# Kubfu's towers (gym package expeditions)
TOWERS = {"urshifu": "the Tower of Darkness", "urshifurapidstrike": "the Tower of Waters"}
# items the dex only names in the evolution condition (Ankimon has the item rows)
ITEM_COND = {"kleavor": "Black Augurite", "ursaluna": "Peat Block", "alcremie": "Sweet"}


def _key(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def ability_desc(ability) -> str:
    """Rich-text tooltip for an ability ("" if unknown)."""
    global _abilities
    if _abilities is None:
        try:
            with open(os.path.join(_ADDON, "data_files", "ability_text.json"), encoding="utf-8") as f:
                _abilities = json.load(f)
        except Exception:
            _abilities = {}
    a = _abilities.get(_key(ability))
    if not a:
        return ""
    return "<b>%s</b><br>%s" % (a["name"], str(a.get("desc") or "").replace("Pokemon", "Pokémon"))


def _article(item) -> str:
    return ("an " if str(item)[:1].lower() in "aeiou" else "a ") + str(item)


def _trade_rule():
    try:
        from ..wild import wild_rules as W
        return int(W.TRADE_EVO_LEVEL), int(W.TRADE_EVO_FRIENDSHIP)
    except Exception:
        return 37, 160


def _one(evo, level, single):
    """One evolution as text. single: a full sentence; otherwise "how -> Name"."""
    from .pokedex_functions import _load_pokedex_cache
    d = (_load_pokedex_cache() or {}).get(_key(evo)) or {}
    name = d.get("name") or str(evo)
    t, lv = d.get("evoType"), d.get("evoLevel")
    item, cond, move = d.get("evoItem"), d.get("evoCondition"), d.get("evoMove")
    if not item and _key(evo) in ITEM_COND:
        item, t, cond = ITEM_COND[_key(evo)], "useItem", None
    when = (", %s" % cond) if cond else ""      # no brackets: the pixel font draws them as @
    if _key(evo) in TOWERS:
        how, full = "Clear %s" % TOWERS[_key(evo)], "Clear %s in Expeditions to evolve into %s" % (TOWERS[_key(evo)], name)
    elif not t and lv:
        lv = int(lv)
        if level < lv:
            how, full = "Lv %d%s" % (lv, when), "Raise to Lv %d to evolve into %s%s" % (lv, name, when)
        else:
            how, full = "next level-up%s" % when, "Evolves into %s on its next level-up%s" % (name, when)
    elif t in ("useItem", "trade", "levelHold") and item:     # held-item level-ups: used like a stone
        how, full = _article(item), "Use %s to evolve into %s" % (_article(item), name)
    elif t == "trade":
        tl, tf = _trade_rule()
        how = "Lv %d + %d friendship" % (tl, tf)
        full = "Evolves into %s at Lv %d with %d friendship, no trade needed" % (name, tl, tf)
    elif t == "levelFriendship":
        how, full = "high friendship%s" % when, "Evolves into %s with high friendship%s" % (name, when)
    else:
        if t == "levelMove" and move:
            game = "levelling up knowing %s" % move
        elif t == "levelHold" and item:
            game = "levelling up holding %s%s" % (_article(item), when)
        else:
            game = str(cond or "a special condition").rstrip(".")
            game = game[:1].lower() + game[1:]
        how = "%s - not in Ankimon yet" % game
        full = "Evolves into %s by %s in the games - not in Ankimon yet" % (name, game)
    return full if single else "%s → %s" % (how, name)


def evolution_hint(species_id, level, everstone=False) -> str:
    """The line for the details window ("" if the species is unknown)."""
    try:
        from .pokedex_functions import _load_pokedex_cache, search_pokedex_by_id
        dex = _load_pokedex_cache() or {}
        d = dex.get(_key(search_pokedex_by_id(int(species_id)))) or {}
    except Exception:
        return ""
    if not d:
        return ""
    evos = list(d.get("evos") or [])
    if not d.get("forme"):
        # a normal-form Pokemon evolves into the normal form here (Pikachu's
        # Thunder Stone gives Raichu, not Alolan Raichu)
        normal = [e for e in evos if (dex.get(_key(e)) or {}).get("forme") not in ("Alola", "Galar", "Hisui", "Paldea")]
        evos = normal or evos
    if not evos:
        return "Fully evolved"
    if everstone:
        return "Holding an Everstone: it won't evolve"
    level = int(level or 1)
    if len(evos) == 1:
        return _one(evos[0], level, True)
    lines = [_one(e, level, False) for e in evos[:3]]
    if len(evos) > 3:
        lines.append("+%d more" % (len(evos) - 3))
    return "Evolves:\n" + "\n".join(lines)
