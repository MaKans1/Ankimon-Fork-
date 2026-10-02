from ..functions.sprite_functions import get_sprite_path
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QPushButton, QScrollArea, QGroupBox, QFrame, QGridLayout, QComboBox, QDialogButtonBox, QCheckBox, QWidget
from PyQt6.QtGui import QPixmap
import json
import os
from aqt import mw
from aqt.utils import showInfo, showWarning
from ..resources import mypokemon_path, frontdefault, team_pokemon_path

class PokemonTeamDialog(QDialog):
    def __init__(self, settings_obj, logger, trainer_card=None, parent=mw):
        super().__init__(parent)

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Choose Your Pokémon Team (Max 6 Pokémon)")
        self.settings = settings_obj
        self.logger = logger
        self.trainer_card = trainer_card

        # Set the minimum size of the dialog
        self.setMinimumSize(900, 500)  # Minimum size of 900x500 pixels

        # Load the Pokémon team data
        self.my_pokemon = self.load_my_pokemon()
        self.team_pokemon = [None] * 6  # Assuming a team can hold 6 Pokémon
        self.team_pokemon = self.load_pokemon_team()

        # Layout
        layout = QVBoxLayout()

        # Label
        label = QLabel("Choose your Pokémon team (up to 6 Pokémon):")
        layout.addWidget(label)

        # Team selection area (scrollable)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        team_widget = QGroupBox()
        team_layout = QGridLayout()  # Change this to QGridLayout for grid arrangement

        # Create a frame for each Pokémon in the team
        self.pokemon_frames = []
        for i in range(6):
            row = i // 3  # Determine the row (0 or 1)
            col = i % 3  # Determine the column (0, 1, or 2)

            frame = QFrame()
            frame.setFrameShape(QFrame.Shape.StyledPanel)
            frame.setFrameShadow(QFrame.Shadow.Raised)

            pokemon_layout = QVBoxLayout()

            # Label for Pokémon name and level
            pokemon_label = QLabel(f"Pokémon {i+1}: Not Selected")
            pokemon_layout.addWidget(pokemon_label)

            # Add Pokémon sprite preview
            sprite_label = QLabel()
            pokemon_layout.addWidget(sprite_label)

            # "Switch out Pokémon" button
            switch_button = QPushButton(f"Switch out Pokémon {i+1}")
            switch_button.clicked.connect(lambda _, i=i: self.switch_out_pokemon(i))
            pokemon_layout.addWidget(switch_button)

            # "Remove Pokémon" button
            remove_button = QPushButton(f"Remove Pokémon {i+1}")
            remove_button.clicked.connect(lambda _, i=i: self.remove_pokemon(i))
            pokemon_layout.addWidget(remove_button)

            frame.setLayout(pokemon_layout)
            team_layout.addWidget(frame, row, col)  # Add frame to grid layout at specific row and column
            self.pokemon_frames.append({'frame': frame, 'label': pokemon_label, 'sprite': sprite_label, 'switch_button': switch_button, 'remove_button': remove_button})

        team_widget.setLayout(team_layout)
        scroll_area.setWidget(team_widget)
        layout.addWidget(scroll_area)

        # XP Share + adventure buddy: a button showing the current choice.
        # Clicking opens the standard picker (same as "Switch out"); Cancel
        # keeps the current choice.
        self._sprite_cache = {}
        _all_iids = {p['individual_id'] for p in self.my_pokemon if p}
        _xp = self.settings.get("trainer.xp_share")
        self.xp_share_iid = _xp if _xp in _all_iids else None
        try:
            self.buddy_iid = (mw.ankimon_db.get_main_pokemon() or {}).get("individual_id")
        except Exception:
            self.buddy_iid = None
        self.buddy_changed = False

        layout.addWidget(QLabel("Choose Pokémon with XP Share:"))
        self.xp_share_button = QPushButton()
        self.xp_share_button.clicked.connect(self._choose_xp_share)
        layout.addWidget(self.xp_share_button)

        layout.addWidget(QLabel("Adventure buddy (auto-battles during reviews):"))
        self.buddy_button = QPushButton()
        self.buddy_button.clicked.connect(self._choose_buddy)
        layout.addWidget(self.buddy_button)
        self._refresh_choice_buttons()

        # OK Button
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.on_ok)
        layout.addWidget(ok_button)

        # Set layout
        self.setLayout(layout)

        # Initialize team with current Pokémon data
        self.update_team_display()

        self.exec()

    def load_my_pokemon(self):
        """Load the player's Pokémon data from database using lightweight stubs"""
        cursor = mw.ankimon_db.execute("""
            SELECT individual_id, 
                   name as name,
                   level as level,
                   pokedex_id as id,
                   shiny as shiny,
                   json_extract(data, '$.gender') as gender,
                   json_extract(data, '$.type') as type,
                   json_extract(data, '$.nickname') as nickname
            FROM captured_pokemon
            ORDER BY individual_id ASC
        """)
        
        my_pokemon = []
        for row in cursor.fetchall():
            my_pokemon.append({
                "individual_id": row[0],
                "name": row[1],
                "level": row[2],
                "id": row[3],
                "shiny": bool(row[4]),
                "gender": row[5],
                # json_extract returns the JSON text, e.g. '["Dark","Fire"]';
                # _types_of parses it. Without this the type filter has
                # nothing to match on and every box shows 0 results.
                "type": row[6] if len(row) > 6 else None,
                "nickname": row[7] if len(row) > 7 else None,
            })
        return my_pokemon

    def _search_entry(self, p):
        """One Pokémon as a poke_search entry (sprites cached per look)."""
        from ..functions import poke_search as PS
        look = (p.get('id'), bool(p.get('shiny')), p.get('gender'))
        pix = self._sprite_cache.get(look)
        if pix is None:
            try:
                pix = QPixmap(get_sprite_path("front", "png", p['id'], p["shiny"], p["gender"]))
            except Exception:
                pix = None
            self._sprite_cache[look] = pix
        types = PS.parse_types(p.get('type'))
        tl = PS.type_label(types)
        return {"key": p['individual_id'], "data": p['individual_id'],
                "label": f"{p['name']} (Level {p['level']})" + (f" - {tl}" if tl else ""),
                "name": p.get('name'), "nickname": p.get('nickname') or "",
                "types": types, "level": p.get('level'), "icon": pix}

    def load_pokemon_team(self):
        """Load the player's Pokémon Team from the database"""
        team_data = mw.ankimon_db.get_team()
        matching_pokemon = []

        for pokemon_in_team in team_data:
            individual_id = pokemon_in_team.get('individual_id')
            if individual_id:
                pokemon = mw.ankimon_db.get_pokemon(individual_id)
                if pokemon:
                    matching_pokemon.append(pokemon)

        return matching_pokemon

    def update_team_display(self):
        """Update the display with the player's current team"""
        # Ensure team_pokemon has 6 slots (pad with None if less than 6)
        max_pokemon_slots = 6
        self.team_pokemon = self.team_pokemon[:max_pokemon_slots]  # Trim to a max of 6 Pokémon
        self.team_pokemon.extend([None] * (max_pokemon_slots - len(self.team_pokemon)))  # Pad with None if less than 6

        for i, frame_data in enumerate(self.pokemon_frames):
            # Check if a Pokémon is selected for this slot (i.e., it's not None)
            if self.team_pokemon[i] is not None:
                pokemon = self.team_pokemon[i]
                pokemon_name = pokemon['name']
                pokemon_level = pokemon['level']
                sprite_path = os.path.join(frontdefault, f"{pokemon['id']}.png")

                # Update label with name and level
                frame_data['label'].setText(f"{pokemon_name} (Level {pokemon_level})")

                # Display the sprite image
                if os.path.exists(sprite_path):
                    pixmap = QPixmap(sprite_path)
                    frame_data['sprite'].setPixmap(pixmap.scaled(50, 50))  # Resize sprite for preview
                    frame_data['sprite'].setAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    frame_data['sprite'].clear()
            else:
                frame_data['label'].setText("Pokémon Not Selected")
                frame_data['sprite'].clear()  # Clear the sprite if not selected

    # ANKIMON_TYPE_FILTER
    POKEMON_TYPES = [
        "Normal", "Fire", "Water", "Electric", "Grass", "Ice",
        "Fighting", "Poison", "Ground", "Flying", "Psychic", "Bug",
        "Rock", "Ghost", "Dragon", "Dark", "Steel", "Fairy",
    ]

    @staticmethod
    def _types_of(pokemon):
        """Types for one Pokémon, normalised to a set.

        The team window loads lightweight stubs where `type` arrives straight
        from json_extract as JSON TEXT, e.g. '["Dark","Fire"]'. Treating that
        as a plain string made every filter match nothing, so parse it first.
        Real lists and bare strings are still accepted.
        """
        t = pokemon.get("type") if pokemon else None
        if t is None:
            return set()
        if isinstance(t, str):
            s = t.strip()
            if s.startswith("["):
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, (list, tuple)):
                        return {str(x) for x in parsed}
                except (ValueError, TypeError):
                    pass
            return {s} if s else set()
        if isinstance(t, (list, tuple, set)):
            return {str(x) for x in t}
        return set()

    # --- the standard Pokemon picker ------------------------------------
    def _pokemon_by_iid(self, iid):
        return next((p for p in self.my_pokemon if p and p['individual_id'] == iid), None)

    def _refresh_choice_buttons(self):
        from PyQt6.QtGui import QIcon
        from PyQt6.QtCore import QSize
        rows = ((self.xp_share_button, self.xp_share_iid, "No XP Share"),
                (self.buddy_button, self.buddy_iid, "No buddy set"))
        for btn, iid, empty in rows:
            p = self._pokemon_by_iid(iid) if iid else None
            if p:
                e = self._search_entry(p)
                text, icon = e["label"], e["icon"]
            else:
                text, icon = empty, None
            btn.setText(text + "      (click to change)")
            btn.setIcon(QIcon(icon) if icon is not None and not icon.isNull() else QIcon())
            btn.setIconSize(QSize(32, 32))
            btn.setStyleSheet("text-align: left; padding: 6px 10px;")

    def _choose_xp_share(self):
        action, p = self._pick_pokemon("Choose Pokémon with XP Share",
                                       [x for x in self.my_pokemon if x],
                                       current_iid=self.xp_share_iid,
                                       clear_label="No XP Share")
        if action == "pick" and p:
            self.xp_share_iid = p['individual_id']
        elif action == "clear":
            self.xp_share_iid = None
        self._refresh_choice_buttons()

    def _choose_buddy(self):
        action, p = self._pick_pokemon("Choose Adventure Buddy",
                                       [x for x in self.my_pokemon if x],
                                       current_iid=self.buddy_iid)
        if action == "pick" and p:
            self.buddy_iid = p['individual_id']
            self.buddy_changed = True
        self._refresh_choice_buttons()

    def _pick_pokemon(self, title, candidates, current_iid=None, clear_label=None):
        """Search (name / nickname / type), type checkboxes, dropdown and
        preview. Returns ("pick", pokemon), ("clear", None), or (None, None)
        when cancelled. Listed A-Z; a search keeps that order."""
        from ..functions import poke_search as PS
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumSize(380, 560)
        layout = QVBoxLayout()
        result = {"action": None, "pokemon": None}

        available_pokemon = sorted(
            [p for p in candidates if p],
            key=lambda p: (str(p.get('name') or '').lower(), -int(p.get('level') or 0)))

        search = PS.make_search_edit()
        layout.addWidget(QLabel("Search:"))
        layout.addWidget(search)

        layout.addWidget(QLabel("Filter by type:"))
        show_all = QCheckBox("Show all")
        show_all.setChecked(True)
        layout.addWidget(show_all)

        hint = QLabel("Tick any combination. Dual types match either box, so "
                      "an Electric/Steel appears under both.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint)

        type_boxes = {}
        grid = QGridLayout()
        for i, tname in enumerate(self.POKEMON_TYPES):
            cb = QCheckBox(tname)
            type_boxes[tname] = cb
            grid.addWidget(cb, i // 3, i % 3)
        grid_holder = QWidget()
        grid_holder.setLayout(grid)
        layout.addWidget(grid_holder)

        combo_box = QComboBox()
        layout.addWidget(QLabel("Choose a Pokémon:"))
        layout.addWidget(combo_box)

        layout.addWidget(QLabel("Preview:"))
        image_label = QLabel()
        layout.addWidget(image_label)

        count_label = QLabel("")
        count_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(count_label)

        first_fill = {"done": False}

        def matching():
            picked = {t for t, cb in type_boxes.items() if cb.isChecked()}
            if show_all.isChecked() or not picked:
                base = list(available_pokemon)
            else:
                base = [p for p in available_pokemon if picked & self._types_of(p)]
            return PS.filter_sorted(base, search.text(), lambda p: p.get('name'),
                                    lambda p: p.get('nickname'), lambda p: p.get('type'),
                                    lambda p: p.get('level'))

        def update_preview(index):
            pokemon = combo_box.itemData(index)
            if pokemon:
                sprite_path = get_sprite_path("front", "png", pokemon['id'],
                                              pokemon["shiny"], pokemon["gender"])
                image_label.setPixmap(QPixmap(sprite_path).scaled(
                    100, 100, Qt.AspectRatioMode.KeepAspectRatio))
                image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            else:
                image_label.clear()

        def refill():
            combo_box.blockSignals(True)
            combo_box.clear()
            subset = matching()
            if subset:
                for pokemon in subset:
                    e = self._search_entry(pokemon)
                    combo_box.addItem(e["label"], pokemon)
                    if e["icon"] is not None:
                        combo_box.setItemData(combo_box.count() - 1, e["icon"],
                                              Qt.ItemDataRole.DecorationRole)
                count_label.setText("%d of %d Pokémon shown"
                                    % (len(subset), len(available_pokemon)))
                if not first_fill["done"] and current_iid:
                    for i in range(combo_box.count()):
                        d = combo_box.itemData(i)
                        if d and d.get('individual_id') == current_iid:
                            combo_box.setCurrentIndex(i)
                            break
            else:
                combo_box.addItem("No Pokémon match this search", None)
                count_label.setText("0 of %d Pokémon shown" % len(available_pokemon))
            first_fill["done"] = True
            combo_box.blockSignals(False)
            update_preview(combo_box.currentIndex())

        def on_show_all(checked):
            if checked:
                for cb in type_boxes.values():
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)
            refill()

        def on_type_toggled():
            if any(cb.isChecked() for cb in type_boxes.values()):
                show_all.blockSignals(True)
                show_all.setChecked(False)
                show_all.blockSignals(False)
            refill()

        show_all.toggled.connect(on_show_all)
        for cb in type_boxes.values():
            cb.toggled.connect(on_type_toggled)
        search.textChanged.connect(lambda _t: refill())
        search.returnPressed.connect(combo_box.showPopup)
        combo_box.currentIndexChanged.connect(
            lambda: update_preview(combo_box.currentIndex()))
        refill()

        def on_ok():
            p = combo_box.itemData(combo_box.currentIndex())
            if p:
                result["action"], result["pokemon"] = "pick", p
            dialog.accept()

        def on_clear():
            result["action"] = "clear"
            dialog.accept()

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                      QDialogButtonBox.StandardButton.Cancel)
        if clear_label:
            clear_btn = QPushButton(clear_label)
            button_box.addButton(clear_btn, QDialogButtonBox.ButtonRole.ResetRole)
            clear_btn.clicked.connect(on_clear)
        button_box.accepted.connect(on_ok)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        dialog.setLayout(layout)
        search.setFocus()
        dialog.exec()
        return result["action"], result["pokemon"]

    def switch_out_pokemon(self, slot):
        """Choose a Pokémon for this slot with the standard picker."""
        used = [p['individual_id'] for i, p in enumerate(self.team_pokemon)
                if p is not None and i != slot]
        available = [p for p in self.my_pokemon if p and p['individual_id'] not in used]
        cur = self.team_pokemon[slot]
        action, pokemon = self._pick_pokemon(
            "Select Pokémon to Switch In", available,
            current_iid=cur.get('individual_id') if cur else None)
        if action == "pick" and pokemon:
            self.team_pokemon[slot] = pokemon
            self.update_team_display()

    def confirm_switch(self, selected_index, slot, dialog):
        """Confirm the Pokémon switch and update the team"""
        # Get the selected Pokémon from combo_box.itemData()
        selected_pokemon = dialog.findChild(QComboBox).itemData(selected_index)

        if selected_pokemon:
            self.team_pokemon[slot] = selected_pokemon  # Replace the Pokémon in the team slot

            # Update the team display
            self.update_team_display()

        dialog.accept()

    def remove_pokemon(self, slot):
        """Remove the Pokémon from the team and handle XP Share if necessary"""
        # Check if there's a Pokémon in the selected slot
        if self.team_pokemon[slot] is not None:
            # Check if the Pokémon in this slot is the one with XP Share
            pokemon_individual_id = self.team_pokemon[slot]['individual_id']
            xp_share_pokemon_individual_id = self.settings.get("trainer.xp_share")

            if pokemon_individual_id in (xp_share_pokemon_individual_id, self.xp_share_iid):
                # Remove XP Share from the Pokémon if it exists
                self.settings.set("trainer.xp_share", None)
                self.xp_share_iid = None
                self._refresh_choice_buttons()

            # Remove the Pokémon from the team slot
            self.team_pokemon[slot] = None

            # Update the display after removal
            self.update_team_display()

    def on_ok(self):
        """Store the selected Pokémon team and XP Share setting, then close the dialog"""
        #team = [frame_data['label'].text() for frame_data in self.pokemon_frames if frame_data['label'].text() != "Pokémon Not Selected"]
        team_data = []  # Initialize the list to store selected Pokémon

        # Process each Pokémon frame to construct the team
        for frame_data in self.team_pokemon:
            if frame_data:  # Ensure the Pokémon has a name
                # Restructure Pokémon data to the desired format
                pokemon_data = {
                    "individual_id": frame_data['individual_id']
                }
                team_data.append(pokemon_data)

        pokemon_names = []

        for frame_data in self.team_pokemon:
            if frame_data:
                # Restructure Pokémon data to the desired format
                pokemon_name = {
                    "name": frame_data['name']
                }
                pokemon_names.append(pokemon_name)

        # Get the selected Pokémon for XP Share
        xp_share_individual_id = self.xp_share_iid
        _xp_mon = self._pokemon_by_iid(xp_share_individual_id) if xp_share_individual_id else None
        xp_share_pokemon = (f"{_xp_mon['name']} (Level {_xp_mon['level']})"
                            if _xp_mon else "No XP Share")

        # Update settings with the selected team and XP Share setting
        self.settings.set("trainer.team", team_data)
        self.settings.set("trainer.xp_share", xp_share_individual_id)  # Save XP Share Pokémon

        try:
            mw.ankimon_db.save_team(team_data)

            self.logger.log_and_showinfo("info", "Trainer settings saved to database.")
            self.logger.log_and_showinfo("info", f"You chose the following team: [{', '.join([pokemon['name'] for pokemon in pokemon_names])}]\nXP Share: {xp_share_pokemon}")
        except Exception as e:
            self.logger.log_and_showinfo("error", f"Failed to save trainer settings: {e}")

        # --- apply the adventure buddy choice ------------------------------
        # set_main_pokemon flips is_main in the DB; update_main_pokemon then
        # refreshes the live singleton IN PLACE (via update_stats), so every
        # module holding a reference sees the new buddy without a restart.
        try:
            _buddy_iid = self.buddy_iid if self.buddy_changed else None
            _buddy_mon = self._pokemon_by_iid(_buddy_iid) if _buddy_iid else None
            _buddy_name = (f"{_buddy_mon['name']} (Level {_buddy_mon['level']})"
                           if _buddy_mon else "")
            if _buddy_iid:
                if mw.ankimon_db.set_main_pokemon(_buddy_iid):
                    from ..functions.update_main_pokemon import update_main_pokemon
                    from ..singletons import main_pokemon as _mp
                    update_main_pokemon(_mp)
                    self.logger.log_and_showinfo(
                        "info", f"Adventure buddy set to {_buddy_name}.")
                else:
                    self.logger.log_and_showinfo(
                        "error", "Could not set that Pokémon as your buddy.")
        except Exception as e:
            self.logger.log_and_showinfo("error", f"Failed to set buddy: {e}")

        # Reload trainer card team data when confirmed new team
        if self.trainer_card is not None:
            self.trainer_card.reload_team()

        self.accept()  # Close the dialog
