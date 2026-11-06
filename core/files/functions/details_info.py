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
    if t == "levelMove" and not lv:             # move evolutions: a set level in Ankimon (2026-11-03)
        from .pokedex_functions import move_evo_level
        lv = move_evo_level(_key(evo)) or None
        if lv:
            t = None
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
        full = "Evolves into %s %s%s in the games - not in Ankimon yet" % (    # not "by with a..." (Sylveon)
            name, "" if game.startswith("with ") else "by ", game)
    return full if single else "%s → %s" % (how, name)


def evolution_pages(species_id, level, friendship=0, live_friendship=True, moves=None) -> list:
    """Each evolution's requirement, A-Z, for the details window's arrows (user
    2026-11-04): [{"id", "name", "text"}]; [] unless it has two or more. Friendship
    evolutions say how much friendship is left (and the time of day) when that
    feature is on - Sylveon also says whether it knows a Fairy-type move and how
    to learn one; the rest use the same sentence as a single evolution."""
    try:
        from .pokedex_functions import _load_pokedex_cache, search_pokedex_by_id
        dex = _load_pokedex_cache() or {}
        d = dex.get(_key(search_pokedex_by_id(int(species_id)))) or {}
    except Exception:
        return []
    evos = list(d.get("evos") or [])
    if not d.get("forme"):                      # as evolution_hint: normal forms evolve into normal forms
        normal = [e for e in evos if (dex.get(_key(e)) or {}).get("forme") not in ("Alola", "Galar", "Hisui", "Paldea")]
        evos = normal or evos
    if len(evos) < 2:
        return []
    live = {}
    if live_friendship:
        try:
            from . import friendship_evolution as FE
            tod = FE.get_time_of_day()
            fevos = list(FE.get_friendship_evolutions_for_species(int(species_id)) or [])
            fr = int(friendship or 0)
            have = FE.known_move_types(moves) if hasattr(FE, "known_move_types") else {}
            gated = [e for e in fevos if getattr(e, "move_type", None)]
            gated_ok = [e for e in gated if e.move_type in have]
            plain = [e for e in fevos if not getattr(e, "move_type", None)]
            for e in gated:                     # Sylveon: 160 friendship + a Fairy-type move (Gen 8-9)
                need = max(0, int(e.min_happiness) - fr)
                typ = e.move_type.capitalize()
                if e.move_type in have:
                    live[int(e.evo_id)] = ("Ready to evolve into %s! It knows %s" % (e.evo_name, have[e.move_type])
                                           if need == 0 else "%d friendship to evolve into %s - it knows %s"
                                           % (need, e.evo_name, have[e.move_type]))
                else:
                    hint = FE.move_learn_hint(int(species_id), e.move_type)
                    head = ("Learn a %s move to evolve into %s, day or night" % (typ, e.evo_name) if need == 0 else
                            "%d friendship + a %s move to evolve into %s, day or night" % (need, typ, e.evo_name))
                    live[int(e.evo_id)] = head + (". Learns %s" % hint if hint else "")
            # the others: only the ones Evolve now can give (by day / by night)
            reach = {int(FE._select_evolution(plain, t).evo_id) for t in ("day", "night")} if plain else set()
            for e in plain:
                if int(e.evo_id) not in reach:
                    continue
                if gated_ok:                    # a known Fairy move wins over the time of day
                    g = gated_ok[0]
                    live[int(e.evo_id)] = "It knows %s, so it becomes %s instead of %s" % (
                        have[g.move_type], g.evo_name, e.evo_name)
                    continue
                need = max(0, int(e.min_happiness) - fr)
                ok = e.time_of_day is None or e.time_of_day == tod
                live[int(e.evo_id)] = FE._build_status_text(
                    everstone=False, ready=need == 0 and ok, evo_name=e.evo_name, friendship_remaining=need,
                    required_time=e.time_of_day, time_ok=ok, time_of_day=tod)
        except Exception:
            live = {}
    level = int(level or 1)
    pages = []
    for e in evos:
        x = dex.get(_key(e)) or {}
        sid = int(x.get("species_id") or x.get("num") or 0)
        try:
            text = live.get(sid) or _one(e, level, True)
        except Exception:
            continue
        pages.append({"id": sid, "name": str(x.get("name") or e), "text": text})
    pages.sort(key=lambda p: p["name"].lower())
    return pages if len(pages) > 1 else []


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
