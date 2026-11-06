"""
held_picker.py - equip a held item from the Pokémon window (user 2026-11-04).

The "Held item" line is a button. It opens the holdable items in your bag that
help this Pokémon, grouped by kind (power items, plates, type boosters,
berries...). The groups with the best pick come first, and so do the best items
in each group. Items that wouldn't help it, or only in odd cases, are left out.
"Usable" means: a plate or booster only for a type it attacks with, a resist
berry only for a type it's weak to, Eviolite only if it can still evolve, and a
weather rock only if it sets that weather. Picking one equips it; the item it
held goes back to the bag.
"""
import json
import os

from aqt import mw
from aqt.qt import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QWidget, QPixmap,
                    QFrame, Qt)

PLATES = {"flame-plate": "Fire", "splash-plate": "Water", "zap-plate": "Electric", "meadow-plate": "Grass",
          "icicle-plate": "Ice", "fist-plate": "Fighting", "toxic-plate": "Poison", "earth-plate": "Ground",
          "sky-plate": "Flying", "mind-plate": "Psychic", "insect-plate": "Bug", "stone-plate": "Rock",
          "spooky-plate": "Ghost", "draco-plate": "Dragon", "dread-plate": "Dark", "iron-plate": "Steel",
          "pixie-plate": "Fairy"}
BOOSTERS = {"silver-powder": "Bug", "metal-coat": "Steel", "soft-sand": "Ground", "hard-stone": "Rock",
            "miracle-seed": "Grass", "black-glasses": "Dark", "black-belt": "Fighting", "magnet": "Electric",
            "mystic-water": "Water", "sharp-beak": "Flying", "poison-barb": "Poison", "never-melt-ice": "Ice",
            "spell-tag": "Ghost", "twisted-spoon": "Psychic", "charcoal": "Fire", "dragon-fang": "Dragon",
            "silk-scarf": "Normal", "sea-incense": "Water", "odd-incense": "Psychic", "rock-incense": "Rock",
            "wave-incense": "Water", "rose-incense": "Grass", "fairy-feather": "Fairy"}
GEMS = {"%s-gem" % t.lower(): t for t in ("Fire", "Water", "Electric", "Grass", "Ice", "Fighting", "Poison",
                                          "Ground", "Flying", "Psychic", "Bug", "Rock", "Ghost", "Dark", "Steel",
                                          "Dragon", "Normal", "Fairy")}
RESIST = {"occa-berry": "Fire", "passho-berry": "Water", "wacan-berry": "Electric", "rindo-berry": "Grass",
          "yache-berry": "Ice", "chople-berry": "Fighting", "kebia-berry": "Poison", "shuca-berry": "Ground",
          "coba-berry": "Flying", "payapa-berry": "Psychic", "tanga-berry": "Bug", "charti-berry": "Rock",
          "kasib-berry": "Ghost", "haban-berry": "Dragon", "colbur-berry": "Dark", "babiri-berry": "Steel",
          "roseli-berry": "Fairy"}
SIGNATURE = {"light-ball": (("pikachu",), "Doubles its Attack and Sp. Atk"),
             "thick-club": (("cubone", "marowak", "marowakalola"), "Doubles its Attack"),
             "lucky-punch": (("chansey",), "Its attacks land critical hits far more often"),
             "stick": (("farfetchd", "sirfetchd"), "Its attacks land critical hits far more often"),
             "leek": (("farfetchd", "sirfetchd"), "Its attacks land critical hits far more often"),
             "metal-powder": (("ditto",), "Doubles its Defense"),
             "quick-powder": (("ditto",), "Doubles its Speed"),
             "deep-sea-tooth": (("clamperl",), "Doubles its Sp. Atk"),
             "deep-sea-scale": (("clamperl",), "Doubles its Sp. Def"),
             "soul-dew": (("latios", "latias"), "Its Psychic and Dragon moves hit 20% harder"),
             "adamant-orb": (("dialga",), "Its Dragon and Steel moves hit 20% harder"),
             "lustrous-orb": (("palkia",), "Its Dragon and Water moves hit 20% harder"),
             "griseous-orb": (("giratina",), "Its Dragon and Ghost moves hit 20% harder"),
             "rusted-sword": (("zacian",), "Becomes Zacian, Crowned Sword"),
             "rusted-shield": (("zamazenta",), "Becomes Zamazenta, Crowned Shield")}
WEATHER = {"heat-rock": ("sunnyday", ("drought", "orichalcumpulse"), "sun"),
           "damp-rock": ("raindance", ("drizzle",), "rain"),
           "icy-rock": ("hail", ("snowwarning",), "snow"),
           "smooth-rock": ("sandstorm", ("sandstream", "sandspit"), "sandstorm")}
SURGE = ("electricsurge", "psychicsurge", "grassysurge", "mistysurge", "hadronengine", "seedsower")
GUTS_LIKE = {"flame-orb": ("guts", "flareboost", "marvelscale", "quickfeet"),
             "toxic-orb": ("poisonheal", "toxicboost", "guts", "marvelscale", "quickfeet")}

# group -> heading (groups are shown best-first; this is only the tie order)
GROUPS = ["Signature items", "Power items", "Plates", "Type boosters", "Defense and recovery", "Berries",
          "Battle tools", "Gems", "Z-Crystals", "Tera Shards", "Training"]
MIN_SCORE = 20          # below this an item is too niche to list


def _key(s):
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


_CHART = None


def _chart():
    global _CHART
    if _CHART is None:
        try:
            from ..resources import effectiveness_chart_file_path as p
            _CHART = json.load(open(p, encoding="utf-8"))
        except Exception:
            _CHART = {}
    return _CHART


_MOVES = None


def _move(k):
    """Showdown move data (data_files/moves.json: "Ice", "Special"). Not the wild
    engine's table - that one writes types and categories in lower case."""
    global _MOVES
    if _MOVES is None:
        try:
            from ..resources import moves_file_path as p
            _MOVES = json.load(open(p, encoding="utf-8"))
        except Exception:
            _MOVES = {}
    return _MOVES.get(k)


def _eff(att, types):
    out = 1.0
    for t in types:
        out *= float((_chart().get(att) or {}).get(t, 1))
    return out


class Profile:
    """What a Pokémon fights with: types, base stats, ability and the moves it uses."""

    def __init__(self, rec, moves):
        from ..functions.pokedex_functions import _load_pokedex_cache
        rec = rec or {}
        self.name = rec.get("name") or "?"
        dex = (_load_pokedex_cache() or {}).get(_key(self.name)) or {}
        self.key = _key(self.name)
        self.types = [str(t).capitalize() for t in (rec.get("type") or dex.get("types") or [])]
        bs = dex.get("baseStats") or {}
        g = lambda k: int(bs.get(k) or 70)
        self.atk, self.spa, self.spe = g("atk"), g("spa"), g("spe")
        self.bulk = (g("hp") + g("def") + g("spd")) / 3.0
        self.dfn = g("def")
        self.nfe = bool(dex.get("evos"))
        self.ability = _key(rec.get("ability"))
        self.ids, self.moves = [], []
        for m in moves:
            k = _key(m)
            if k and k not in self.ids:
                self.ids.append(k)
                self.moves.append(_move(k) or {})
        self.dmg = []                       # (move id, move, weight)
        for k, m in zip(self.ids, self.moves):
            if str(m.get("category")) == "Status":
                continue
            bp = int(m.get("basePower") or 0) or 60          # Low Kick, Seismic Toss...: about 60
            hits = m.get("multihit")
            if isinstance(hits, list):
                bp *= sum(hits) / 2.0
            elif isinstance(hits, int):
                bp *= hits
            acc = m.get("accuracy")
            w = bp * (1.5 if m.get("type") in self.types else 1) * (1 if acc is True else float(acc or 100) / 100)
            self.dmg.append((k, m, w))
        tot = sum(w for _k, _m, w in self.dmg) or 1.0
        self.share = {}
        for _k, m, w in self.dmg:
            self.share[m.get("type")] = self.share.get(m.get("type"), 0) + w / tot
        self.phys = sum(w for _k, m, w in self.dmg if m.get("category") == "Physical") / tot
        self.spec = sum(w for _k, m, w in self.dmg if m.get("category") == "Special") / tot
        self.status = len(self.ids) - len(self.dmg)

    def names(self, test):
        return [m.get("name") or k for k, m, _w in self.dmg if test(m)]

    def knows(self, *ids):
        return any(i in self.ids for i in ids)

    def any_move(self, test):
        return [m.get("name") or k for k, m in zip(self.ids, self.moves) if test(m)]


def _type_item(p, t, base, per, label):
    s = p.share.get(t, 0)
    if s <= 0:
        return None
    moves = ", ".join(p.names(lambda m: m.get("type") == t))
    return base + per * s + (8 if t in p.types else 0), "%s: %s" % (label % t, moves)


def score(item, p):
    """(group, score, why) for this Pokémon, or None if it wouldn't help."""
    i = item
    if i in SIGNATURE:
        users, why = SIGNATURE[i]
        return ("Signature items", 90, why) if p.key in users else None
    if i in PLATES:
        r = _type_item(p, PLATES[i], 20, 40, "Its %s moves hit 20%% harder")
        return ("Plates",) + r if r else None
    if i in BOOSTERS:
        r = _type_item(p, BOOSTERS[i], 20, 40, "Its %s moves hit 20%% harder")
        return ("Type boosters",) + r if r else None
    if i in GEMS:
        r = _type_item(p, GEMS[i], 10, 25, "Its first %s move in a battle hits 30%% harder")
        return ("Gems",) + r if r else None
    if i in RESIST:
        t = RESIST[i]
        e = _eff(t, p.types)
        if e < 2:
            return None
        return ("Berries", 40 if e >= 4 else 30,
                "Halves the first super-effective %s hit (%s)" % (t, "4x weak" if e >= 4 else "weak to %s" % t))
    if i in WEATHER:
        mv, abil, word = WEATHER[i]
        if p.knows(mv) or p.ability in abil:
            return "Battle tools", 30, "Its %s lasts 8 turns instead of 5" % word
        return None
    if i in GUTS_LIKE:
        if p.ability in GUTS_LIKE[i] or p.knows("facade"):
            return "Battle tools", 45, ("Burns it on purpose - its ability or Facade turns that into power"
                                        if i == "flame-orb" else
                                        "Poisons it on purpose - its ability or Facade turns that into power")
        return None
    dmg = len(p.dmg)
    if i == "life-orb":
        return ("Power items", 60, "All its attacks hit 30% harder; it loses a little HP each time") if dmg else None
    if i == "expert-belt":
        kinds = len({m.get("type") for _k, m, _w in p.dmg})
        return ("Power items", 40, "Super-effective hits do 20% more (it attacks with %d types)" % kinds) \
            if kinds >= 2 else None
    if i == "choice-band":
        return ("Power items", 60 * p.phys, "Physical moves hit 50% harder, but it's locked into one move") \
            if p.phys >= 0.6 else None
    if i == "choice-specs":
        return ("Power items", 60 * p.spec, "Special moves hit 50% harder, but it's locked into one move") \
            if p.spec >= 0.6 else None
    if i == "choice-scarf":
        return ("Power items", 35 if 60 <= p.spe <= 110 else 22, "50% more Speed, but it's locked into one move") \
            if dmg else None
    if i == "muscle-band":
        return ("Power items", 35 * p.phys, "Physical moves hit 10% harder") if p.phys >= 0.6 else None
    if i == "wise-glasses":
        return ("Power items", 35 * p.spec, "Special moves hit 10% harder") if p.spec >= 0.6 else None
    if i == "eviolite":
        return ("Defense and recovery", 60, "Defense and Sp. Def x1.5 while it can still evolve") if p.nfe else None
    if i == "leftovers":
        return "Defense and recovery", 30 + max(0, min(20, (p.bulk - 70) / 2)), "Restores a little HP every turn"
    if i == "black-sludge":
        return ("Defense and recovery", 45, "Restores a little HP every turn (Poison types only)") \
            if "Poison" in p.types else None
    if i == "assault-vest":
        return ("Defense and recovery", 35, "Sp. Def x1.5; it can only attack (no status moves)") \
            if dmg and not p.status else None
    if i == "focus-sash":
        return ("Defense and recovery", 35, "Survives one knockout hit at full HP with 1 HP") if p.bulk < 75 else None
    if i == "rocky-helmet":
        return ("Defense and recovery", 25, "Hurts attackers that touch it") if p.dfn >= 90 else None
    if i == "shell-bell":
        return ("Defense and recovery", 25, "Heals 1/8 of the damage it deals") if dmg >= 3 else None
    if i == "weakness-policy":
        return ("Defense and recovery", 30, "A super-effective hit sharply raises Attack and Sp. Atk") \
            if p.bulk >= 85 else None
    if i == "air-balloon":
        e = _eff("Ground", p.types)
        return ("Defense and recovery", 40 if e >= 4 else 30, "Immune to Ground moves until it's hit") \
            if e >= 2 else None
    if i == "big-root":
        mv = p.any_move(lambda m: m.get("drain"))
        return ("Defense and recovery", 30, "Its draining moves heal 30% more: " + ", ".join(mv)) if mv else None
    if i == "sitrus-berry":
        return "Berries", 40, "Heals 1/4 of its HP when it drops below half"
    if i in ("figy-berry", "wiki-berry", "mago-berry", "aguav-berry", "iapapa-berry"):
        return "Berries", 30, "Heals 1/3 of its HP when it drops low"
    if i == "lum-berry":
        return "Berries", 35, "Cures one status problem (or confusion)"
    if i == "chesto-berry":
        return ("Berries", 45, "Wakes it straight up after Rest") if p.knows("rest") else None
    if i == "liechi-berry":
        return ("Berries", 25, "Raises Attack when its HP drops low") if p.phys >= 0.5 else None
    if i == "petaya-berry":
        return ("Berries", 25, "Raises Sp. Atk when its HP drops low") if p.spec >= 0.5 else None
    if i == "salac-berry":
        return ("Berries", 25, "Raises Speed when its HP drops low") if dmg else None
    if i in ("ganlon-berry", "apicot-berry"):
        return ("Berries", 22, "Raises %s when its HP drops low" % ("Defense" if i == "ganlon-berry" else "Sp. Def")) \
            if p.bulk >= 85 else None
    if i in ("scope-lens", "razor-claw"):
        mv = p.any_move(lambda m: int(m.get("critRatio") or 1) >= 2)
        return ("Battle tools", 35, "More critical hits, on top of its high-crit moves: " + ", ".join(mv)) if mv else None
    if i == "wide-lens":
        mv = p.any_move(lambda m: m.get("accuracy") is not True and int(m.get("accuracy") or 100) < 100
                        and m.get("category") != "Status")
        return ("Battle tools", 30, "Its moves hit 10% more often: " + ", ".join(mv)) if mv else None
    if i == "zoom-lens":
        mv = p.any_move(lambda m: m.get("accuracy") is not True and int(m.get("accuracy") or 100) < 100)
        return ("Battle tools", 25, "More accurate when it moves last: " + ", ".join(mv)) if mv and p.spe < 60 else None
    if i == "quick-claw":
        return ("Battle tools", 25, "Sometimes lets it move first") if p.spe < 50 else None
    if i == "white-herb":
        mv = p.any_move(lambda m: any(v < 0 for v in ((m.get("self") or {}).get("boosts") or {}).values())
                        or m.get("id") == "shellsmash")
        return ("Battle tools", 40, "Undoes the stat drops from " + ", ".join(mv)) if mv else None
    if i == "power-herb":
        mv = p.any_move(lambda m: (m.get("flags") or {}).get("charge"))
        return ("Battle tools", 45, "Skips the charging turn of " + ", ".join(mv)) if mv else None
    if i == "light-clay":
        mv = p.any_move(lambda m: m.get("sideCondition") in ("reflect", "lightscreen", "auroraveil"))
        return ("Battle tools", 35, "Its screens last 8 turns: " + ", ".join(mv)) if mv else None
    if i == "terrain-extender":
        mv = p.any_move(lambda m: m.get("terrain"))
        return ("Battle tools", 30, "Its terrain lasts 8 turns") if mv or p.ability in SURGE else None
    if i in ("binding-band", "grip-claw"):
        mv = p.any_move(lambda m: m.get("volatileStatus") == "partiallytrapped")
        if not mv:
            return None
        return ("Battle tools", 30 if i == "binding-band" else 25,
                ("Its binding moves hurt more: " if i == "binding-band" else "Its binding moves last longer: ")
                + ", ".join(mv))
    if i == "loaded-dice":
        mv = p.any_move(lambda m: m.get("multihit"))
        return ("Battle tools", 35, "Its multi-hit moves hit more times: " + ", ".join(mv)) if mv else None
    if i == "punching-glove":
        mv = p.any_move(lambda m: (m.get("flags") or {}).get("punch"))
        return ("Battle tools", 25, "Its punches hit 10% harder: " + ", ".join(mv)) if mv else None
    if i == "booster-energy":
        return ("Battle tools", 50, "Powers up its Paradox ability") \
            if p.ability in ("protosynthesis", "quarkdrive") else None
    if i == "lucky-egg":
        return "Training", 30, "Earns 1.5x EXP"
    if i.endswith("-tera-shard"):
        t = i[:-len("-tera-shard")].capitalize()
        if t in p.types and p.share.get(t):
            return "Tera Shards", 35, "Paldea battles: Terastallizing into %s makes its %s moves even stronger" % (t, t)
        if p.share.get(t):
            return "Tera Shards", 30, "Paldea battles: Terastallizing into %s gives its %s moves the same-type bonus" % (t, t)
        return None
    try:
        from ..gym import zmoves
        t = zmoves.crystal_type(i)
        if t:
            if not zmoves.can_use_crystal({"attacks": list(p.ids)}, i):
                return None
            return ("Z-Crystals", 30 + (10 if t in p.types else 0),
                    "Alola gym battles: one %s move becomes a Z-Move, once per battle" % t)
    except Exception:
        pass
    return None


def curate(rec, moves, bag):
    """[(group, [(item, qty, score, why)])] - best group first, best item first in each."""
    p = Profile(rec, moves)
    groups = {}
    for item, qty in bag.items():
        r = score(item, p)
        if r and r[1] >= MIN_SCORE:
            groups.setdefault(r[0], []).append((item, qty, r[1], r[2]))
    out = []
    for g, rows in groups.items():
        rows.sort(key=lambda x: (-x[2], x[0]))
        out.append((g, rows))
    out.sort(key=lambda gr: (-gr[1][0][2], GROUPS.index(gr[0]) if gr[0] in GROUPS else 99))
    return out


def bag_items():
    out = {}
    try:
        for it in mw.ankimon_db.get_all_items() or []:
            n, q = str(it.get("item_name") or "").lower(), int(it.get("quantity") or 0)
            if n and q > 0:
                out[n] = out.get(n, 0) + q
    except Exception as e:
        print("Ankimon: couldn't read the bag:", e)
    return out


def equip(iid, item, live=None):
    """Give item to the saved Pokémon iid (None = take its item off); the old one
    goes back to the bag. live: the buddy object, kept in step."""
    from ..pyobj.pokemon_obj import PokemonObject
    rec = mw.ankimon_db.get_pokemon(iid)
    if not rec:
        return False
    obj = PokemonObject.from_dict(rec)
    if item:
        obj.give_held_item(item)
    else:
        obj.remove_held_item()
    if live is not None and getattr(live, "individual_id", None) == iid:
        live.held_item = item or None
    return True


def _label(item):
    try:
        from ..utils import item_display_name
        return item_display_name(item)
    except Exception:
        return str(item).replace("-", " ").title()


def _icon(item, size=32):
    try:
        from ..resources import items_path
        pm = QPixmap(os.path.join(str(items_path), "%s.png" % item))
        if not pm.isNull():
            lab = QLabel()
            lab.setPixmap(pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
            lab.setFixedWidth(size + 6)
            return lab
    except Exception:
        pass
    lab = QLabel("")
    lab.setFixedWidth(size + 6)
    return lab


class HeldPicker(QDialog):
    """The curated list. moves: everything it fights with (full + scaled)."""

    def __init__(self, parent, iid, moves, live=None):
        super().__init__(parent or mw)
        self.iid, self.live, self.changed = iid, live, False
        rec = mw.ankimon_db.get_pokemon(iid) or {}
        name = rec.get("nickname") or _label(rec.get("name") or "?")
        self.setWindowTitle("Held item - %s" % name)
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        held = rec.get("held_item")
        top = QHBoxLayout()
        top.addWidget(QLabel("Holding: <b>%s</b>" % (_label(held) if held else "nothing")))
        top.addStretch(1)
        if held:
            off = QPushButton("Take it off")
            off.clicked.connect(lambda: self._pick(None))
            top.addWidget(off)
        v.addLayout(top)
        groups = curate(rec, moves, bag_items())
        if not groups:
            v.addWidget(QLabel("Nothing in your bag would help %s right now." % name))
        else:
            body = QWidget()
            b = QVBoxLayout(body)
            b.setContentsMargins(0, 0, 8, 0)
            for g, rows in groups:
                h = QLabel("<b>%s</b>" % g)
                h.setContentsMargins(0, 8, 0, 2)
                b.addWidget(h)
                for item, qty, _s, why in rows:
                    row = QHBoxLayout()
                    row.addWidget(_icon(item))
                    txt = QLabel("%s%s<br><span style='color:gray'>%s</span>"
                                 % (_label(item), "  x%d" % qty if qty > 1 else "", why))
                    txt.setWordWrap(True)
                    row.addWidget(txt, 1)
                    eq = QPushButton("Equip")
                    eq.clicked.connect(lambda _c=False, it=item: self._pick(it))
                    row.addWidget(eq)
                    b.addLayout(row)
            b.addStretch(1)
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.Shape.NoFrame)
            sc.setWidget(body)
            sc.setMinimumHeight(min(560, 90 + 56 * sum(len(r) for _g, r in groups)))
            v.addWidget(sc, 1)
        foot = QHBoxLayout()
        foot.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        foot.addWidget(close)
        v.addLayout(foot)

    def _pick(self, item):
        try:
            if equip(self.iid, item, self.live):
                self.changed = True
        except Exception as e:
            print("Ankimon: couldn't change the held item:", e)
        self.accept()
