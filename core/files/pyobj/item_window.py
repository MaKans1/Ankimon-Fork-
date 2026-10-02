from pathlib import Path
import random
import json
import csv
from typing import Any, Optional

from aqt import mw
from aqt.qt import (
    QGridLayout,
    QPixmap,
    Qt,
)
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QComboBox,
    QLineEdit,
    QScrollArea,
    QInputDialog,
)

from ..pyobj.evolution_window import EvoWindow
from ..pyobj.InfoLogger import ShowInfoLogger
from ..pyobj.pc_box import GiveItemWindow
from ..pyobj.pokemon_obj import PokemonObject
from ..pyobj.settings import Settings
from ..pyobj.starter_window import StarterWindow

from ..business import (
    get_id_and_description_by_item_name
)
from ..functions.pokedex_functions import (
    search_pokedex_by_id,
    return_id_for_item_name,
    check_evolution_by_item,
    find_details_move
)

from ..resources import icon_path, items_path, csv_file_items_cost, poke_evo_path
from ..functions.badges_functions import check_for_badge, receive_badge
from ..functions.pokemon_functions import save_fossil_pokemon
from ..utils import play_effect_sound
from .error_handler import show_warning_with_traceback

# At the moment when I write this line, "UserRole" is defined as UserRole 1000 in the Ankimon __init__.py file. IDK what it's about.
UserRole = 1000

class ItemWindow(QWidget):
    def __init__(
            self,
            logger: ShowInfoLogger,
            settings_obj: Settings,
            main_pokemon: PokemonObject,
            enemy_pokemon: PokemonObject,
            achievements: dict[str, bool],
            starter_window: StarterWindow,
            evo_window: EvoWindow,
            ):
        super().__init__()
        self.logger: ShowInfoLogger = logger
        self.settings_obj: Settings = settings_obj
        self.main_pokemon: PokemonObject = main_pokemon
        self.enemy_pokemon: PokemonObject = enemy_pokemon
        self.achievements: dict[str, bool] = achievements
        self.starter_window: StarterWindow = starter_window
        self.evo_window: EvoWindow = evo_window
        self._item_action_in_progress = False
        self._pokemon_choices_cache = None
        self.initUI()

    def initUI(self):
        self.hp_heal_items = {
            'potion': 20,
            'sweet-heart': 20,
            'berry-juice': 20,
            'fresh-water': 30,
            'soda-pop': 50,
            'super-potion': 60,
            'energy-powder': 60,
            'lemonade': 70,
            'moomoo-milk': 100,
            'hyper-potion': 120,
            'energy-root': 120,
            'full-restore': 1000,
            'max-potion': 1000
        }

        self.fossil_pokemon = {
            "helix-fossil": 138,
            "dome-fossil": 140,
            "old-amber": 142,
            "root-fossil": 345,
            "claw-fossil": 347,
            "skull-fossil": 408,
            "armor-fossil": 410,
            "cover-fossil": 564,
            "plume-fossil": 566
        }

        self.pokeball_chances = {
            'dive-ball': 11,      # Increased chance when fishing or underwater
            'dusk-ball': 11,      # Increased chance at night or in caves
            'great-ball': 12,     # Increased catch rate (original was 9, now 12)
            'heal-ball': 12,      # Same as a Poké Ball but heals the Pokémon
            'iron-ball': 12,      # Used for Steel-type Pokémon, 1.5x chance
            'light-ball': 1,      # Not actually used for catching Pokémon; it's an item
            'luxury-ball': 12,    # Same as a Poké Ball but increases happiness
            'master-ball': 100,   # Guarantees a successful catch (100% chance)
            'nest-ball': 12,      # Works better on lower-level Pokémon
            'net-ball': 12,       # Higher chance for Water- and Bug-type Pokémon
            'poke-ball': 8,       # Increased chance from 5 to 8
            'premier-ball': 8,    # Same as Poké Ball, but it's a special ball
            'quick-ball': 13,     # High chance if used at the start of battle
            'repeat-ball': 12,    # Higher chance on Pokémon that have been caught before
            'safari-ball': 8,     # Used in Safari Zone, with a fixed catch rate
            'smoke-ball': 1,      # Used to flee from wild battles, no catch chance
            'timer-ball': 13,     # Higher chance the longer the battle goes
            'ultra-ball': 13      # Increased catch rate (original was 10, now 13)
        }

        self.evolution_items = set()
        self.load_evolution_items()

        self.setWindowIcon(QIcon(str(icon_path)))  # Add a Pokeball icon
        self.setWindowTitle("Itembag")
        self.layout = QVBoxLayout()  # Main layout is now a QVBoxLayout

        # Search Filter
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search Items...")
        self.search_edit.returnPressed.connect(self.filter_items)
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.filter_items)

        # Add dropdown menu for generation filtering
        self.category = QComboBox()
        self.category.addItem("All")
        self.category.addItems(["Fossils", "TMs and HMs", "Heal", "Evolution Items", "Berries", "Battle Items"])
        self.category.currentIndexChanged.connect(self.filter_items)

        # Add widgets to layout
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(self.search_edit)
        filter_layout.addWidget(self.search_button)
        filter_layout.addWidget(self.category)
        self.layout.addLayout(filter_layout)

        # Create the scroll area and its properties
        self.scrollArea = QScrollArea(self)
        self.scrollArea.setWidgetResizable(True)

        # Create a widget and layout for content inside the scroll area
        self.contentWidget = QWidget()
        self.contentLayout = QGridLayout()  # The layout for items

        # FIX 1: Set equal column stretches for consistent column widths
        self.contentLayout.setColumnStretch(0, 1)  # Column 0 gets stretch factor 1
        self.contentLayout.setColumnStretch(1, 1)  # Column 1 gets stretch factor 1
        self.contentLayout.setColumnStretch(2, 1)  # Column 2 gets stretch factor 1

        # FIX 2: Set minimum column widths to ensure consistent sizing
        min_column_width = 200  # Adjust this value as needed
        self.contentLayout.setColumnMinimumWidth(0, min_column_width)
        self.contentLayout.setColumnMinimumWidth(1, min_column_width)
        self.contentLayout.setColumnMinimumWidth(2, min_column_width)

        # Set uniform spacing
        self.contentLayout.setHorizontalSpacing(10)
        self.contentLayout.setVerticalSpacing(10)

        self.contentWidget.setLayout(self.contentLayout)

        # Add the content widget to the scroll area
        self.scrollArea.setWidget(self.contentWidget)

        # Add the scroll area to the main layout
        self.layout.addWidget(self.scrollArea)
        self.setLayout(self.layout)

        # FIX 3: Increase initial window size to better accommodate 3 columns
        # Calculate appropriate width: 3 columns * min_width + spacing + margins
        initial_width = 3 * min_column_width + 2 * 10 + 40  # 3 cols + 2 spacings + margins
        initial_height = 600  # Increased from 500
        self.resize(initial_width, initial_height)

    def renewWidgets(self):
        # Clear the existing widgets from the content layout
        for i in reversed(range(self.contentLayout.count())):
            widget = self.contentLayout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        row, col = 0, 0
        max_items_per_row = 3

        itembag_list = self._normalize_item_entries(self.read_items_file())
        if not itembag_list:  # Simplified check
            empty_label = QLabel("You don't own any items yet.")
            self.contentLayout.addWidget(empty_label, 1, 1)
        else:
            for item in itembag_list:
                try:
                    item_widget = self.ItemLabel(item["item"], item["quantity"], item.get("type"))
                    item_widget.setMinimumWidth(180)
                    self.contentLayout.addWidget(item_widget, row, col)
                    col += 1
                    if col >= max_items_per_row:
                        row += 1
                        col = 0
                except Exception as e:
                    self.logger.log("error", f"Skipping invalid item '{item}': {e}")

    def filter_items(self):
        search_text = self.search_edit.text().lower()
        category_index = self.category.currentIndex()
        # Clear the existing widgets from the content layout
        for i in reversed(range(self.contentLayout.count())):
            widget = self.contentLayout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        row, col = 0, 0
        max_items_per_row = 3

        filtered_items = self._normalize_item_entries(self.read_items_file())
        if not filtered_items:
            empty_label = QLabel("You don't own any items yet.")
            self.contentLayout.addWidget(empty_label, 1, 1)
            return

        try:
            # Filter items based on category index
            if category_index == 1:  # Fossils
                filtered_items = [
                    item for item in filtered_items
                    if isinstance(item, dict) and "item" in item and item["item"] in self.fossil_pokemon
                ]
            elif category_index == 2:  # TMs and HMs
                filtered_items = list(filter(lambda item: item.get("type") == "TM", filtered_items))
            elif category_index == 3:  # Heal items
                filtered_items = [
                    item for item in filtered_items
                    if isinstance(item, dict) and "item" in item and (item["item"] in self.hp_heal_items
                                                                       or item["item"] in self.HEAL_BERRIES)
                ]
            elif category_index == 4:  # Evolution items
                filtered_items = [
                    item for item in filtered_items
                    if isinstance(item, dict) and "item" in item and item["item"] in self.evolution_items
                ]
            elif category_index == 5:  # Berries
                filtered_items = [item for item in filtered_items
                                  if str(item.get("item", "")).endswith("-berry")]
            elif category_index == 6:  # Battle items (X items, cures, revives, PP)
                battle = set(self.X_ITEMS) | set(self.CURES) | set(self.REVIVES) | set(self.PP_ITEMS)
                filtered_items = [item for item in filtered_items if item.get("item") in battle]

            # Now filter by search
            filtered_items = list(filter(lambda item: search_text in item["item"].lower(), filtered_items))
        except Exception as e:
            filtered_items = []
            self.logger.log_and_showinfo("error", f"Error filtering items: {e}")

        if not filtered_items:
            empty_label = QLabel("Empty Search")
            self.contentLayout.addWidget(empty_label, 1, 1)
            return

        for item in filtered_items:
            try:
                item_widget = self.ItemLabel(item["item"], item["quantity"], item.get("type"))
                item_widget.setMinimumWidth(180)
                self.contentLayout.addWidget(item_widget, row, col)
                col += 1
                if col >= max_items_per_row:
                    row += 1
                    col = 0
            except Exception as e:
                self.logger.log("error", f"Skipping invalid item '{item}': {e}")

    def give_held_item(self, comboBox, item_name):
        individual_id = comboBox.itemData(comboBox.currentIndex(), role=UserRole)
        self._give_held_item_by_id(individual_id, item_name)

    def _give_held_item_by_id(self, individual_id, item_name):
        if not individual_id:
            self.logger.log_and_showinfo("error", "No Pokémon selected.")
            return
        try:
            db = mw.ankimon_db
            target_pokemon_data = db.get_pokemon(individual_id)

            if target_pokemon_data:
                pokemon_obj = PokemonObject.from_dict(target_pokemon_data)
                pokemon_obj.give_held_item(item_name)
                self.logger.log_and_showinfo("info", f"{item_name} was given to {target_pokemon_data.get('name')}.")
                self.renewWidgets()
            else:
                self.logger.log_and_showinfo("error", "Could not find Pokémon data.")

        except Exception as e:
            self.logger.log_and_showinfo("error", f"Error giving item: {e}")

    # ------------------------------------------------------------------
    # Item tiles (Ankimon 2.0): sprite + name + one action. Hover the sprite
    # (or name) for the item's description - no "More Info" button. Every
    # item has a real use, or a greyed button that says where it's used.
    # ------------------------------------------------------------------
    HEAL_BERRIES = {"oran-berry": 10, "berry-juice": 20, "sitrus-berry": -25, "figy-berry": -33,
                    "wiki-berry": -33, "mago-berry": -33, "aguav-berry": -33, "iapapa-berry": -33,
                    "enigma-berry": -25}          # negative = percent of max HP
    CURES = {"antidote": ("psn", "tox"), "paralyze-heal": ("par",), "awakening": ("slp",),
             "burn-heal": ("brn",), "ice-heal": ("frz",), "full-heal": None, "lava-cookie": None,
             "old-gateau": None, "casteliacone": None, "lumiose-galette": None, "shalour-sable": None,
             "big-malasada": None, "pewter-crunchies": None, "rage-candy-bar": None, "jubilife-muffin": None,
             "heal-powder": None, "cheri-berry": ("par",), "chesto-berry": ("slp",),
             "pecha-berry": ("psn", "tox"), "rawst-berry": ("brn",), "aspear-berry": ("frz",),
             "lum-berry": None, "persim-berry": ("confusion",)}
    REVIVES = ("revive", "max-revive", "revival-herb")
    PP_ITEMS = ("ether", "max-ether", "elixir", "max-elixir", "leppa-berry")
    X_ITEMS = {"x-attack": "attack_boost", "x-defense": "defense_boost", "x-sp-atk": "special_attack_boost",
               "x-sp-def": "special_defense_boost", "x-speed": "speed_boost", "x-accuracy": "accuracy_boost",
               "dire-hit": "focusenergy", "guard-spec": "mist"}
    X_STAGE_KEYS = {"attack_boost": "atk", "defense_boost": "def", "special_attack_boost": "spa",
                    "special_defense_boost": "spd", "speed_boost": "spe", "accuracy_boost": "accuracy"}
    BATTLE_BERRIES = {  # held effects the battle engines apply
        "occa", "passho", "wacan", "rindo", "yache", "chople", "kebia", "shuca", "coba", "payapa",
        "tanga", "charti", "kasib", "haban", "colbur", "babiri", "chilan", "roseli", "liechi",
        "ganlon", "salac", "petaya", "apicot", "lansat", "starf", "micle", "custap", "jaboca",
        "rowap", "kee", "maranga"}
    EV_BERRIES = {"pomeg-berry": "hp", "kelpsy-berry": "atk", "qualot-berry": "def",
                  "hondew-berry": "spa", "grepa-berry": "spd", "tamato-berry": "spe"}

    def _buddy_name(self):
        try:
            from ..functions.pokedex_functions import display_name
            return self.main_pokemon.nickname or display_name(self.main_pokemon.name)
        except Exception:
            return "your Pokémon"

    def _item_tooltip(self, item_name, item_type):
        if item_type == "TM":
            try:
                from ..pyobj.attack_dialog import move_tooltip
                tip = move_tooltip(item_name) or ""
            except Exception:
                tip = ""
            return (tip + "<br><br>" if tip else "") + (
                "Teach this move to a Pokémon that can learn it. TMs are not used up.")
        try:
            from ..utils import get_item_description
            d = get_item_description(item_name, self.settings_obj.get("misc.language"))
        except Exception:
            d = None
        if not d:
            try:
                d = get_id_and_description_by_item_name(item_name)
            except Exception:
                d = None
        return str(d or item_name.replace("-", " ").title())

    def _action_button(self, text, enabled=True, why="", fn=None):
        b = QPushButton(text)
        b.setEnabled(bool(enabled))
        # Item tiles are narrow: a long label (a long nickname) is shortened
        # with "..." instead of being clipped at both ends; full text on hover.
        fm = b.fontMetrics()
        if fm.horizontalAdvance(text) > 150:
            b.setText(fm.elidedText(text, Qt.TextElideMode.ElideRight, 150))
            why = text + ("\n" + why if why else "")
        if why:
            b.setToolTip(why)
        if fn is not None and enabled:
            b.clicked.connect(lambda _c=False: fn())
        return b

    def ItemLabel(self, item_name: str, quantity: int, item_type: Optional[str]):
        item_frame = QVBoxLayout()
        label = item_name.replace("-", " ").title()
        if item_type == "TM":
            label = "TM %s" % label
        tip = self._item_tooltip(item_name, item_type)
        if item_type == "TM":
            details = find_details_move(item_name) or {}
            item_file_path = items_path / ("Bag_TM_%s_SV_Sprite.png" % str(details.get("type", "Normal")).lower())
        else:
            item_file_path = items_path / ("%s.png" % item_name)
        pm = QPixmap(str(item_file_path)).scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation)
        pic = QLabel()
        pic.setPixmap(pm)
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pic.setToolTip(tip)
        name = QLabel("%s  ×%d" % (label, quantity))
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setToolTip(tip)
        item_frame.addWidget(pic)
        item_frame.addWidget(name)
        for w in self._item_actions(item_name.lower(), item_type):
            item_frame.addWidget(w)
        holder = QWidget()
        holder.setLayout(item_frame)
        return holder

    def _item_actions(self, item, item_type):
        """The button(s) for one item."""
        mp = self.main_pokemon
        buddy = self._buddy_name()
        if item_type == "TM":
            return [self._action_button("Teach…", fn=lambda: self._teach_tm(item))]
        if item in self.hp_heal_items or item in self.HEAL_BERRIES:
            full = int(mp.hp) >= int(mp.max_hp)
            out = [self._action_button("Heal %s" % buddy, not full, "Already at full HP" if full else "",
                                       lambda: self._use_heal(item))]
            if item.endswith("-berry"):
                out.append(self._action_button("Give to hold", fn=lambda: self._prompt_and_give_held_item(item)))
            return out
        if item in self.CURES:
            cures = self.CURES[item]
            st = str(getattr(mp, "battle_status", "") or "").lower()
            vol = set(getattr(mp, "volatile_status", None) or ())
            ok = (st in ("par", "brn", "slp", "frz", "psn", "tox") and (cures is None or st in cures)) or \
                 (cures and "confusion" in cures and "confusion" in vol)
            out = [self._action_button("Cure %s" % buddy, ok, "" if ok else "Nothing to cure right now",
                                       lambda: self._use_cure(item))]
            if item.endswith("-berry"):
                out.append(self._action_button("Give to hold", fn=lambda: self._prompt_and_give_held_item(item)))
            return out
        if item in self.REVIVES:
            fainted = self._fainted_teammates()
            return [self._action_button("Revive a teammate", bool(fainted),
                                        "" if fainted else "No team member has fainted in this battle. "
                                        "(Revives also work between Expedition floors.)",
                                        lambda: self._use_revive(item))]
        if item in self.PP_ITEMS:
            out = [self._action_button("Restore PP", False,
                                       "Wild battles don't use PP. Use it between Expedition floors.")]
            if item.endswith("-berry"):
                out.append(self._action_button("Give to hold", fn=lambda: self._prompt_and_give_held_item(item)))
            return out
        if item in self.X_ITEMS:
            return [self._action_button("Use in battle", True, "Boosts %s for the rest of this battle." % buddy,
                                        lambda: self._use_x_item(item))]
        if item in self.fossil_pokemon:
            fossil_id = self.fossil_pokemon[item]
            fossil_name = search_pokedex_by_id(fossil_id)
            return [self._action_button("Revive %s" % _pname(fossil_name),
                                        fn=lambda: self.Evolve_Fossil(item, fossil_id, fossil_name))]
        if item in self.evolution_items:
            eligible = self._evo_candidates(item)
            any_ok = any(e["enabled"] for e in eligible)
            why = "" if eligible else "None of your Pokémon evolve with this item."
            if eligible and not any_ok:
                why = "Your Pokémon that use it aren't a high enough level yet."
            return [self._action_button("Evolve…", bool(eligible), why, lambda: self._prompt_and_check_evo_item(item))]
        if item in self.pokeball_chances:
            return [self._action_button("Throw", False,
                                        "Ankimon catches wild Pokémon when they faint - no Poké Balls needed.")]
        if item in self.EV_BERRIES:
            stat = self.EV_BERRIES[item]
            return [self._action_button("Feed (−10 %s EVs)" % stat.upper(), True,
                                        "Lowers its %s EVs by 10 and raises friendship." % stat.upper(),
                                        lambda: self._feed_berry(item, stat))]
        if item.endswith("-berry") and item[:-6] not in self.BATTLE_BERRIES:
            return [self._action_button("Feed (+friendship)", fn=lambda: self._feed_berry(item, None))]
        return [self._action_button("Give to hold", fn=lambda: self._prompt_and_give_held_item(item))]

    # --- live battle state -------------------------------------------------
    @staticmethod
    def _wild():
        try:
            from ..wild import wild_rules
            return wild_rules
        except Exception:
            return None

    def _fainted_teammates(self):
        W = self._wild()
        try:
            return [i for i in (W.STATE.fainted if W else set()) if mw.ankimon_db.get_pokemon(i)]
        except Exception:
            return []

    def _after_battle_item(self, msg):
        """Rebuild the battle from the Pokémon next turn so the item counts."""
        W = self._wild()
        if W:
            W.reset_battle()
        self.logger.log_and_showinfo("info", msg)
        self.renewWidgets()

    def _use_heal(self, item):
        mp = self.main_pokemon
        amt = self.hp_heal_items.get(item, self.HEAL_BERRIES.get(item, 20))
        if item in ("full-restore", "max-potion", "fullrestore", "maxpotion"):
            amt = mp.max_hp
        elif amt < 0:
            amt = max(1, int(mp.max_hp * (-amt) / 100))
        before = int(mp.hp)
        mp.hp = min(int(mp.max_hp), before + int(amt))
        mp.current_hp = mp.hp
        if item == "full-restore":
            mp.battle_status = "fighting"
        if not check_for_badge(self.achievements, 20):
            receive_badge(20, self.achievements)
        mw.ankimon_db.update_item_quantity(item, -1)
        play_effect_sound(self.settings_obj, "HpHeal")
        self._after_battle_item("%s recovered %d HP." % (self._buddy_name(), mp.hp - before))

    def _use_cure(self, item):
        mp = self.main_pokemon
        if item == "persim-berry":
            mp.volatile_status = set(v for v in (mp.volatile_status or ()) if v != "confusion")
        else:
            mp.battle_status = "fighting"
            if item == "lum-berry":
                mp.volatile_status = set(v for v in (mp.volatile_status or ()) if v != "confusion")
        mw.ankimon_db.update_item_quantity(item, -1)
        self._after_battle_item("%s was cured." % self._buddy_name())

    def _use_revive(self, item):
        W = self._wild()
        fainted = self._fainted_teammates()
        entries = []
        for iid in fainted:
            rec = mw.ankimon_db.get_pokemon(iid) or {}
            entries.append({"key": iid, "label": "%s  Lv %s" % (_pname(rec.get("name")), rec.get("level", "?")),
                            "enabled": True})
        key = self._pick("Revive", entries, "Revive which team member?")
        if not key or not W:
            return
        W.STATE.fainted.discard(key)
        mw.ankimon_db.update_item_quantity(item, -1)
        self.logger.log_and_showinfo("info", "%s is ready to battle again." % _pname((mw.ankimon_db.get_pokemon(key) or {}).get("name")))
        self.renewWidgets()

    def _use_x_item(self, item):
        mp = self.main_pokemon
        W = self._wild()
        what = self.X_ITEMS[item]
        st = None
        try:
            bl = W._battle_loop_state() if W else None
            if bl is not None and getattr(bl, "new_state", None) is not None and getattr(bl, "mutator_full_reset", 1) == 0:
                st = bl.new_state
        except Exception:
            st = None
        if what in self.X_STAGE_KEYS:
            k = self.X_STAGE_KEYS[what]
            stages = dict(getattr(mp, "stat_stages", None) or {})
            stages[k] = min(6, int(stages.get(k, 0)) + 2)
            mp.stat_stages = stages
            if st is not None:
                setattr(st.user.active, what, min(6, int(getattr(st.user.active, what, 0)) + 2))
            msg = "%s's %s rose sharply!" % (self._buddy_name(), item[2:].replace("-", " ").title())
        elif what == "focusenergy":
            mp.volatile_status = set(mp.volatile_status or ()) | {"focusenergy"}
            if st is not None:
                st.user.active.volatile_status.add("focusenergy")
            msg = "%s is getting pumped!" % self._buddy_name()
        else:
            if st is None:
                self.logger.log_and_showinfo("info", "Use Guard Spec. during a wild battle.")
                return
            st.user.side_conditions["mist"] = 5
            msg = "Your team became shrouded in mist!"
        mw.ankimon_db.update_item_quantity(item, -1)
        self.logger.log_and_showinfo("info", msg)
        self.renewWidgets()

    def _feed_berry(self, item, ev_stat):
        key = self._select_pokemon("Feed %s" % item.replace("-", " ").title())
        if not key:
            return
        iid, _pid = key
        rec = mw.ankimon_db.get_pokemon(iid)
        if not rec:
            return
        rec["friendship"] = int(rec.get("friendship") or 0) + 10
        note = "+10 friendship"
        if ev_stat:
            ev = dict(rec.get("ev") or {})
            old = int(ev.get(ev_stat, 0) or 0)
            ev[ev_stat] = max(0, old - 10)
            rec["ev"] = ev
            note += ", %s EVs %d -> %d" % (ev_stat.upper(), old, ev[ev_stat])
        mw.ankimon_db.save_pokemon(rec)
        if getattr(self.main_pokemon, "individual_id", None) == iid:
            self.main_pokemon.friendship = rec["friendship"]
            if ev_stat:
                self.main_pokemon.ev = rec["ev"]
        mw.ankimon_db.update_item_quantity(item, -1)
        self.logger.log_and_showinfo("info", "%s enjoyed the %s! (%s)" % (
            _pname(rec.get("name")), item.replace("-", " ").title(), note))
        self.renewWidgets()

    # --- TMs ---------------------------------------------------------------
    def _teach_tm(self, move):
        try:
            from ..resources import pokemon_tm_learnset_path
            learn = json.load(open(pokemon_tm_learnset_path, encoding="utf-8"))
        except Exception:
            learn = {}
        entries = []
        for rec in mw.ankimon_db.get_all_pokemon() or []:
            if not rec:
                continue
            key = search_pokedex_by_id(rec.get("id"))
            can = move in (learn.get(key) or [])
            if not can:
                continue
            mid = lambda s: "".join(ch for ch in str(s).lower() if ch.isalnum())  # noqa: E731
            knows = mid(move) in [mid(a) for a in rec.get("attacks") or []]
            entries.append({"key": rec.get("individual_id"),
                            "label": "%s  Lv %s" % (rec.get("nickname") or _pname(rec.get("name")), rec.get("level", "?")),
                            "enabled": not knows, "reason": "Already knows it" if knows else ""})
        if not entries:
            self.logger.log_and_showinfo("info", "None of your Pokémon can learn %s." % move.replace("-", " ").title())
            return
        iid = self._pick("Teach %s" % move.replace("-", " ").title(), entries, "Teach it to:")
        if not iid:
            return
        from ..gui_classes.pokemon_details import remember_attack
        rec = mw.ankimon_db.get_pokemon(iid) or {}
        remember_attack(iid, list(rec.get("attacks") or []), move, self.logger)

    # --- evolution items ---------------------------------------------------
    @staticmethod
    def _evo_stage(species_id):
        """How many non-baby evolutions a species is from its base form."""
        try:
            from ..functions.pokedex_functions import _load_pokedex_cache, pokemon_key, search_pokedex_by_id
            from ..functions import encounter_data
            dex = _load_pokedex_cache()
            cur = dex.get(search_pokedex_by_id(species_id)) or {}
            n = 0
            while cur.get("prevo"):
                prev = dex.get(pokemon_key(cur["prevo"])) or {}
                if prev.get("species_id") not in encounter_data.BABY:
                    n += 1
                cur = prev
            return n
        except Exception:
            return 1

    def _evo_gate(self, evo_id):
        """Evolution items: Lv 16 for a first evolution, Lv 30 for a second
        (setting: Evolution Items Need A Level)."""
        try:
            on = self.settings_obj.get("evolution.item_level_gate", True)
            if isinstance(on, str):
                on = on.strip().lower() in ("1", "true", "yes", "on")
            if not on:
                return 0
        except Exception:
            pass
        return 30 if self._evo_stage(evo_id) >= 2 else 16

    def _item_evo_target(self, species_id, item_id):
        """Quiet version of check_evolution_by_item (no warning pop-ups)."""
        try:
            from ..functions.pokedex_functions import pokemon_evolves_from_id, get_pokemon_evolution_data
            for evo in pokemon_evolves_from_id(species_id) or []:
                d = get_pokemon_evolution_data(int(evo)) or {}
                trig = str(d.get("evolution_trigger_id") or "")
                if trig == "3" and str(d.get("trigger_item_id") or "") == str(item_id):
                    return int(d["evolved_species_id"])
                if trig == "2" and str(d.get("held_item_id") or "") == str(item_id):
                    return int(d["evolved_species_id"])
        except Exception:
            pass
        return None

    def _evo_candidates(self, item):
        item_id = return_id_for_item_name(item)
        out = []
        try:
            rows = mw.ankimon_db.get_all_pokemon() or []
        except Exception:
            rows = []
        for rec in rows:
            if not rec or not rec.get("id"):
                continue
            evo = self._item_evo_target(int(rec["id"]), item_id)
            if not evo:
                continue
            need = self._evo_gate(evo)
            lv = int(rec.get("level") or 1)
            if rec.get("everstone"):
                ok, why = False, "Holding an Everstone"
            elif lv < need:
                ok, why = False, "Needs Lv %d" % need
            else:
                ok, why = True, ""
            out.append({"key": rec.get("individual_id"), "pid": int(rec["id"]),
                        "label": "%s  Lv %d  →  %s" % (rec.get("nickname") or _pname(rec.get("name")), lv,
                                                       _pname(search_pokedex_by_id(evo))),
                        "enabled": ok, "reason": why})
        return out

    def _prompt_and_check_evo_item(self, item_name: str):
        entries = self._evo_candidates(item_name)
        if not entries:
            self.logger.log_and_showinfo("info", "None of your Pokémon evolve with this item.")
            return
        iid = self._pick("Use %s" % item_name.replace("-", " ").title(), entries, "Evolve which Pokémon?")
        if not iid:
            return
        pid = next(e["pid"] for e in entries if e["key"] == iid)
        self.Check_Evo_Item(iid, pid, item_name)

    # --- a picker whose entries can be greyed out ---------------------------
    def _pick(self, title, entries, prompt):
        from aqt.qt import QDialog, QListWidget, QListWidgetItem, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setMinimumSize(360, 380)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(prompt))
        lst = QListWidget()
        for e in sorted(entries, key=lambda e: (not e.get("enabled", True), e["label"].lower())):
            it = QListWidgetItem(e["label"] + ("" if e.get("enabled", True) else "   (%s)" % e.get("reason", "")))
            it.setData(Qt.ItemDataRole.UserRole, e["key"])
            if not e.get("enabled", True):
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
                it.setToolTip(e.get("reason", ""))
            lst.addItem(it)
        for i in range(lst.count()):
            if lst.item(i).flags() & Qt.ItemFlag.ItemIsEnabled:
                lst.setCurrentRow(i)
                break
        lay.addWidget(lst)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lst.itemDoubleClicked.connect(lambda _i: dlg.accept())
        lay.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted or lst.currentItem() is None:
            return None
        if not (lst.currentItem().flags() & Qt.ItemFlag.ItemIsEnabled):
            return None
        return lst.currentItem().data(Qt.ItemDataRole.UserRole)

    def PokemonList(self, comboBox):
        try:
            db = mw.ankimon_db
            pokemon_list = db.execute("SELECT name, individual_id, pokedex_id FROM captured_pokemon").fetchall()
            if pokemon_list:
                for pokemon in pokemon_list:
                    pokemon_name = pokemon[0]
                    individual_id = pokemon[1]
                    id_ = pokemon[2]
                    if individual_id and id_:  # Ensure the ID exists
                        # Add Pokémon name to comboBox
                        comboBox.addItem(pokemon_name)
                        # Store both individual_id and id as separate data using roles
                        comboBox.setItemData(comboBox.count() - 1, individual_id, role=UserRole)
                        comboBox.setItemData(comboBox.count() - 1, id_, role=UserRole + 1)
        except Exception as e:
            self.logger.log_and_showinfo("error", f"Error loading Pokémon list: {e} {pokemon}")

    def _load_pokemon_choices(self):
        if self._pokemon_choices_cache is not None:
            return self._pokemon_choices_cache
        choices = []
        try:
            db = mw.ankimon_db
            rows = db.execute("SELECT name, individual_id, pokedex_id FROM captured_pokemon").fetchall()
            for row in rows:
                name, individual_id, poke_id = row[0], row[1], row[2]
                if name and individual_id and poke_id:
                    choices.append((f"{name} ({individual_id[:8]})", individual_id, poke_id))
        except Exception as e:
            self.logger.log("error", f"Error loading Pokémon list: {e}")
        self._pokemon_choices_cache = choices
        return choices

    def _select_pokemon(self, title: str):
        """Searchable picker: name, nickname or type ("fire"). Returns
        (individual_id, pokedex_id) or None."""
        from ..functions import poke_search as PS
        try:
            rows = mw.ankimon_db.execute(
                "SELECT name, individual_id, pokedex_id, level, json_extract(data, '$.type'), "
                "json_extract(data, '$.nickname') FROM captured_pokemon").fetchall()
        except Exception as e:
            self.logger.log("error", f"Error loading Pokémon list: {e}")
            rows = []
        entries, by_key = [], {}
        for name, iid, pid, level, types, nick in rows:
            if not (name and iid and pid):
                continue
            tl = PS.type_label(types)
            label = f"{name} (Lv {level})"
            if nick and str(nick).lower() != str(name).lower():
                label += f" '{nick}'"
            if tl:
                label += f" - {tl}"
            entries.append({"key": iid, "label": label, "name": name, "nickname": nick or "",
                            "types": PS.parse_types(types), "level": level})
            by_key[iid] = (iid, pid)
        if not entries:
            self.logger.log_and_showinfo("error", "No Pokémon available.")
            return None
        key = PS.choose_pokemon(self, title, entries)
        return by_key.get(key) if key else None

    def _prompt_and_give_held_item(self, item_name: str):
        selected = self._select_pokemon("Give Item")
        if not selected:
            return
        individual_id, _ = selected
        self._give_held_item_by_id(individual_id, item_name)

    def Evolve_Fossil(self, item_name: str, fossil_id: int, fossil_poke_name: str):
        if self._item_action_in_progress:
            return
        self._item_action_in_progress = True
        try:
            if not isinstance(fossil_id, int):
                raise ValueError(f"Invalid fossil id: {fossil_id}")
            save_fossil_pokemon(fossil_id)
            self._pokemon_choices_cache = None
            self.delete_item(item_name)
            self.starter_window.display_fossil_pokemon(fossil_id, fossil_poke_name)
            from ..singletons import pokemon_pc
            pokemon_pc.refresh_pokemon_grid()
        except Exception as e:
            show_warning_with_traceback(parent=self, exception=e, message=f"Error using fossil item '{item_name}'")
        finally:
            self._item_action_in_progress = False

    def modified_pokeball_chances(self, item_name: str, catch_chance: int):
        # Adjust catch chance based on Pokémon type and Poké Ball
        if item_name == 'net-ball' and ('water' in self.enemy_pokemon.type or 'bug' in self.enemy_pokemon.type):
            catch_chance += 10  # Additional 10% for Water or Bug-type Pokémon
            self.logger.log("game", f"{item_name} gets a bonus for Water/Bug-type Pokémon!")

        elif item_name == 'iron-ball' and 'steel' in self.enemy_pokemon.type:
            catch_chance += 10  # Additional 10% for Steel-type Pokémon
            self.logger.log("game", f"{item_name} gets a bonus for Steel-type Pokémon!")

        elif item_name == 'dive-ball' and 'water' in self.enemy_pokemon.type:
            catch_chance += 10  # Additional 10% for Water-type Pokémon
            self.logger.log("game", f"{item_name} gets a bonus for Water-type Pokémon!")

        return catch_chance

    def Handle_Pokeball(self, item_name: str):
        # Check if the item exists in the pokeball chances
        if item_name in self.pokeball_chances:
            catch_chance = self.pokeball_chances[item_name]
            catch_chance = self.modified_pokeball_chances(item_name, catch_chance)

            # Simulate catching the Pokémon based on the catch chance
            if random.randint(1, 100) <= catch_chance:
                # Pokémon caught successfully
                self.logger.log_and_showinfo("info", f"{item_name} successfully caught the Pokémon!")
                self.delete_item(item_name)  # Delete the Poké Ball after use
            else:
                # Pokémon was not caught
                self.logger.log_and_showinfo("info", f"{item_name} failed to catch the Pokémon.")
                self.delete_item(item_name)  # Still delete the Poké Ball after use
        else:
            self.logger.log_and_showinfo("error", f"{item_name} is not a valid Poké Ball!")

    def delete_item(self, item_name: str):
        # Update database directly for performance
        mw.ankimon_db.update_item_quantity(item_name, -1)
        self.renewWidgets()

    def Check_Heal_Item(self, prevo_name: str, heal_points: int, item_name: str, achievements):
        check = check_for_badge(achievements, 20)
        if check is False:
            receive_badge(20, achievements)
        if item_name == "fullrestore" or item_name == "maxpotion":
            heal_points = self.main_pokemon.max_hp
        self.main_pokemon.hp += heal_points
        if self.main_pokemon.hp > (self.main_pokemon.max_hp):
            self.main_pokemon.hp = self.main_pokemon.max_hp
        self.delete_item(item_name)
        play_effect_sound(self.settings_obj, "HpHeal")
        self.logger.log_and_showinfo("info", f"{prevo_name} was healed for {heal_points}")

    def Check_Evo_Item(self, individual_id: str, prevo_id: str, item_name: str):
        try:
            item_id = return_id_for_item_name(item_name)
            evo_id = check_evolution_by_item(prevo_id, item_id)
            if evo_id:
                # Perform your action when the item matches the Pokémon's evolution item
                self.logger.log_and_showinfo("info", "Pokémon Evolution is fitting !")
                self.evo_window.ask_pokemon_evo(individual_id, prevo_id, evo_id)
            else:
                self.logger.log_and_showinfo("info", "This Pokémon does not need this item.")
        except Exception as e:
            show_warning_with_traceback(parent=self, exception=e, message=f"{e}")

    def load_evolution_items(self):
        try:
            evolution_item_ids = set()
            with open(poke_evo_path, mode='r', newline='', encoding='utf-8') as evo_file:
                reader = csv.DictReader(evo_file)
                for row in reader:
                    # Use-item evolutions (trigger 3) consume trigger_item_id.
                    if row.get('evolution_trigger_id') == '3':
                        item_id = row.get('trigger_item_id')
                        if item_id:
                            evolution_item_ids.add(item_id)
                    # Trade-with-held-item evolutions (trigger 2) need held_item_id.
                    # Ankimon has no trading, so surface the held item as usable
                    # (e.g. Metal Coat -> Steelix/Scizor, Deep Sea Tooth/Scale ->
                    # Huntail/Gorebyss, Dragon Scale -> Kingdra, King's Rock ->
                    # Politoed/Slowking).
                    elif row.get('evolution_trigger_id') == '2':
                        item_id = row.get('held_item_id')
                        if item_id:
                            evolution_item_ids.add(item_id)

            with open(csv_file_items_cost, mode='r', newline='', encoding='utf-8') as items_file:
                reader = csv.DictReader(items_file)
                for row in reader:
                    if row['id'] in evolution_item_ids:
                        self.evolution_items.add(row['identifier'])
            
        except Exception as e:
            self.logger.log_and_showinfo("error", f"Error loading evolution items: {e}")

    def write_items_file(self, itembag_list: list[Any]):
        """Writes items to the database. Legacy method kept for compatibility."""
        db = mw.ankimon_db
        for item in itembag_list:
            item_id = item.get("id")
            item_name = item.get("item") or item.get("item_name", "")
            quantity = item.get("quantity", 1)
            # Pass cached metadata back to database
            db.save_item(
                item_id, 
                item_name, 
                quantity, 
                extra_data=item, 
                category_id=item.get("category_id"),
                cost=item.get("cost"),
                fling_power=item.get("fling_power"),
                fling_effect_id=item.get("fling_effect_id")
            )

    def read_items_file(self):
        """
        Reads the item list from the database.
        Returns items in the expected format for the UI, using SQL columns for efficiency.
        """
        try:
            db = mw.ankimon_db
            items = db.get_all_items()
            # Convert database format to UI format
            result = []
            for item in items:
                # Prioritize SQL columns over JSON blob
                cat_id = item.get("category_id")
                item_type = "TM" if cat_id == 37 else None
                
                # Combine database columns into the UI dictionary (preserving extra_data for legacy)
                item_dict = {
                    "id": item.get("id"),
                    "item": item.get("item_name"),
                    "quantity": item.get("quantity", 1),
                    "type": item_type,
                    "category_id": cat_id,
                    "cost": item.get("cost"),
                    "fling_power": item.get("fling_power"),
                    "fling_effect_id": item.get("fling_effect_id")
                }
                
                # Merge with any existing extra_data for backward compatibility
                if item.get("extra_data"):
                    for k, v in item["extra_data"].items():
                        if k not in item_dict:
                            item_dict[k] = v
                            
                result.append(item_dict)
            return result
        except Exception as e:
            self.logger.log("error", f"Error reading items from database: {e}")
            return []

    def _normalize_item_entries(self, items_data):
        if not isinstance(items_data, list):
            return []
        normalized = []
        for raw in items_data:
            if not isinstance(raw, dict):
                continue
            name = raw.get("item")
            if not isinstance(name, str) or not name.strip():
                continue
            quantity = raw.get("quantity", 1)
            try:
                quantity = int(quantity)
            except Exception:
                quantity = 1
            if quantity < 1:
                continue
            normalized.append({
                **raw,
                "item": name.strip(),
                "quantity": quantity,
            })
        return normalized

    def clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def showEvent(self, event):
        self._pokemon_choices_cache = None
        self.renewWidgets()

    def show_window(self):
        # Get the geometry of the main screen
        main_screen_geometry = mw.geometry()

        # Calculate the position to center the ItemWindow on the main screen
        x = int(main_screen_geometry.center().x() - self.width() // 2)
        y = int(main_screen_geometry.center().y() - self.height() // 2)

        # Move the ItemWindow to the calculated position
        self.move(x, y)

        self.show()

    def more_info_button_act(self, item_name: str):
        description = get_id_and_description_by_item_name(item_name)
        self.logger.log_and_showinfo("info", f"{description}")


def _pname(n):
    """Real Pokémon name for display ("Iron Hands", "Mr. Mime")."""
    try:
        from ..functions.pokedex_functions import display_name
        return display_name(n)
    except Exception:
        s = str(n or "")
        return s[:1].upper() + s[1:]


def _cap1(s):
    """Capitalise the first letter only (keeps "Iron Hands", "Ho-Oh")."""
    s = str(s or "")
    return s[:1].upper() + s[1:]
