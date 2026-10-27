"""
gym_window.py — the gym battle screen.

A gym is a BREAK from reviewing. Reviewing only *offers* it; the fight is
played here, and turns advance because you acted (manual) or the timer ticked
(auto). Close it any time and go back to cards.

ISOLATION — the important part
    Gym and wild mode share NOTHING. Earlier this window copied gym Pokemon
    *into* the main_pokemon / enemy_pokemon singletons so the classic renderer
    would draw them. That leaked: those singletons are the same objects wild
    battles use, so a Pokemon knocked out in a gym came back to wild mode
    still at 0 HP, wearing the gym Pokemon's id.

    Instead we swap TestWindow's *references*. TestWindow holds
    self.main_pokemon / self.enemy_pokemon as plain instance attributes, so
    pointing them at the gym's own PokemonObjects for the duration renders the
    gym fight without any shared object ever being written to. The real
    singletons are never touched, so nothing can leak in either direction.

    The gym's PokemonObjects are themselves built from deep copies of your
    saved records, so gym damage cannot reach the database either.
"""

from typing import List, Optional

from aqt import mw
from aqt.qt import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QWidget, Qt, QTimer, QMessageBox, QToolTip, QCursor, QFont, QFontMetrics,
)

from .gym_state import GymSession
from . import gym_battle as GB
from .move_card import MoveButton, card_info

AUTO_TURN_MS = 1100


def _mid(move) -> str:
    """Showdown's id for a move name ("Thunder Bolt" / "thunderbolt" -> "thunderbolt")."""
    import re
    return re.sub(r"[^a-z0-9]", "", str(move or "").lower())
_STATUS_TAG = {"slp": "SLP", "brn": "BRN", "par": "PAR", "psn": "PSN", "tox": "TOX", "frz": "FRZ"}


def _tags(c, bench=False):
    """ " [SLP, TRAPPED, Atk+1]" for the HP line; status only for the roster.
    Showdown supplies full tags; the classic engine only the status."""
    tags = list(getattr(c, "_tags", None) or [])
    if not tags:
        st = str(getattr(getattr(c, "source", None), "battle_status", "") or "").lower()
        if st in _STATUS_TAG:
            tags = [_STATUS_TAG[st]]
    if bench:
        tags = [t for t in tags if t in _STATUS_TAG.values()]
    return (" [" + ", ".join(tags) + "]") if tags else ""


class GymBattleWindow(QDialog):
    """Playable gym battle. Manual: press 1-4 or click. Auto: advances itself."""

    def __init__(self, session: GymSession, auto: bool, on_finish, parent=None):
        super().__init__(parent or mw)
        self.session = session
        self.auto = auto
        self.on_finish = on_finish
        self._closing = False
        self._released = False

        self.setWindowTitle("%s — %s" % (session.gym.name, session.gym.leader))
        self.setMinimumWidth(600)

        from ..singletons import test_window, ankimon_tracker_obj
        self._tw = test_window
        self._tracker = ankimon_tracker_obj
        # Save the renderer's references so wild mode gets its own back.
        self._orig_main = getattr(test_window, "main_pokemon", None)
        self._orig_enemy = getattr(test_window, "enemy_pokemon", None)

        root = QVBoxLayout(self)
        self.scene_holder = QVBoxLayout()
        root.addLayout(self.scene_holder)
        self._scene: Optional[QWidget] = None

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-weight:600;")
        root.addWidget(self.status)
        # Z / Dynamax / Tera markers in the status line are underlined links:
        # hovering one shows what that mechanic does right now (_mech_tips)
        self._mech_tip = {}
        # always rich text: with no marker in it, Qt's guess was plain text and
        # the &nbsp; spacing showed literally
        self.status.setTextFormat(Qt.TextFormat.RichText)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.status.linkHovered.connect(self._mech_hover)
        self.status.linkActivated.connect(self._mech_hover)

        self.party = QLabel("")
        self.party.setWordWrap(True)
        root.addWidget(self.party)

        self.log = QLabel("")
        self.log.setWordWrap(True)
        self.log.setStyleSheet("color:#9aa4b2;")
        root.addWidget(self.log)

        # --- attack buttons (manual mode) --------------------------------
        self.moves_box = QWidget()
        grid = QGridLayout(self.moves_box)
        grid.setContentsMargins(0, 6, 0, 0)
        self.move_buttons: List[QPushButton] = []
        for i in range(4):
            b = MoveButton("-")                 # a card for normal moves (move_card.py)
            b.setMinimumHeight(34)
            b.clicked.connect(lambda _=False, n=i: self._use_move_index(n))
            grid.addWidget(b, i // 2, i % 2)
            self.move_buttons.append(b)
        root.addWidget(self.moves_box)

        foot = QHBoxLayout()
        # Z-Move toggle (Z-Ring + a held Z-Crystal, Showdown engine): the next
        # move you pick becomes its Z-Move. Hidden whenever it can't be used.
        self.z_btn = QPushButton("✦ Z-Move ready")
        self.z_btn.setCheckable(True)
        self.z_btn.setToolTip("Click, then pick a move marked ✦: it becomes its Z-Move "
                              "(once per battle).")
        self.z_btn.setStyleSheet(
            "QPushButton { background:#f4b400; color:#1b1b1b; font-weight:bold; padding:4px 12px; }"
            "QPushButton:checked { background:#ff7a00; color:#1b1b1b; }")
        self.z_btn.toggled.connect(lambda _on: self._sync_move_buttons())
        self.z_btn.setVisible(False)
        foot.addWidget(self.z_btn)
        # Dynamax toggle (Dynamax Band, Galar fights, Showdown engine): the next
        # move you pick Dynamaxes your Pokemon. Purple, where Z-Moves are gold.
        self.d_btn = QPushButton("◆ Dynamax ready")
        self.d_btn.setCheckable(True)
        self.d_btn.setToolTip("Click, then pick a move: your Pokémon Dynamaxes for 3 turns "
                              "(double HP, Max Moves). Once per battle.")
        self.d_btn.setStyleSheet(
            "QPushButton { background:#7e22ce; color:white; font-weight:bold; padding:4px 12px; }"
            "QPushButton:checked { background:#a855f7; color:white; }")
        self.d_btn.toggled.connect(self._dmax_toggled)
        self.d_btn.setVisible(False)
        foot.addWidget(self.d_btn)
        # Tera toggle (Tera Orb, Paldea fights): the next move you pick
        # Terastallizes your Pokemon into its first type. Cyan.
        self.t_btn = QPushButton("◈ Tera ready")
        self.t_btn.setCheckable(True)
        self.t_btn.setToolTip("Click, then pick a move: your Pokémon Terastallizes into its Tera "
                              "type for the rest of the battle. Once per battle.")
        self.t_btn.setStyleSheet(
            "QPushButton { background:#0e7490; color:white; font-weight:bold; padding:4px 12px; }"
            "QPushButton:checked { background:#22d3ee; color:#0b1220; }")
        self.t_btn.toggled.connect(self._tera_toggled)
        self.t_btn.setVisible(False)
        foot.addWidget(self.t_btn)
        self.mode_btn = QPushButton("")
        self.mode_btn.clicked.connect(self._toggle_mode)
        self.forfeit_btn = QPushButton("Forfeit")
        self.forfeit_btn.clicked.connect(self._forfeit)
        foot.addWidget(self.mode_btn)
        foot.addStretch(1)
        foot.addWidget(self.forfeit_btn)
        root.addLayout(foot)

        self._timer = QTimer(self)
        self._timer.setInterval(AUTO_TURN_MS)
        self._timer.timeout.connect(self._auto_tick)

        self.refresh()
        if self.auto:
            self._timer.start()

    # ------------------------------------------------------- isolation ----
    def _point_renderer_at_gym(self):
        """Aim TestWindow at the gym's own objects. Nothing shared is written."""
        p, l = self.session.player_active, self.session.leader_active
        if p is None or l is None:
            return False
        # Combatant.hp is authoritative; push it onto the object being drawn.
        for c in (p, l):
            try:
                c.source.hp = int(c.hp)
                c.source.current_hp = int(c.hp)
                c.source.max_hp = int(c.max_hp)
            except Exception:
                pass
        self._tw.main_pokemon = p.source
        self._tw.enemy_pokemon = l.source
        return True

    def _release(self):
        """Give the renderer its wild-mode references back. Idempotent, and
        called from BOTH _end() and closeEvent() because QDialog.accept()
        does not fire closeEvent — that gap is what leaked state before."""
        if self._released:
            return
        self._released = True
        try:
            if self._orig_main is not None:
                self._tw.main_pokemon = self._orig_main
            if self._orig_enemy is not None:
                self._tw.enemy_pokemon = self._orig_enemy
        except Exception:
            pass

    # ------------------------------------------------------------ render --
    def _render_scene(self):
        if not self._point_renderer_at_gym():
            return
        try:
            # pokemon_display_battle() bumps the lifetime encounter counter as
            # a side effect; a long gym would otherwise inflate it every turn.
            before = self._tracker.pokemon_encounter
            widget = self._tw.pokemon_display_battle()
            self._tracker.pokemon_encounter = before
        except Exception:
            widget = None
        if widget is None:
            return
        if self._scene is not None:
            self.scene_holder.removeWidget(self._scene)
            self._scene.deleteLater()
        self._scene = widget
        self.scene_holder.addWidget(widget)

    def refresh(self):
        self._render_scene()
        s = self.session
        p, l = s.player_active, s.leader_active
        if p and l:
            # Alola: a small marker while the totem (with its aura) is out
            aura = "  ✦ aura" if (getattr(s.gym, "totem", None) and str(l.name).startswith("Totem ")) else ""
            # Z-Moves: ready for this Pokemon, or already spent this battle
            zmark = ("  ✦ Z ready" if self._zmoves() else
                     "  (Z used)" if getattr(s.engine, "zused", False) else "")
            dm = self._dmax()
            dmark = ("  ◆ Dynamax (%d turn%s left)" % (dm.get("turns", 0), "" if dm.get("turns") == 1 else "s")
                     if dm.get("active") else "  ◆ Dynamax ready" if dm.get("can") else
                     "  (Dynamax used)" if (dm.get("used") and dm.get("allowed")) else "")
            foe_d = "  ◆ Dynamaxed" if dm.get("foe") else ""
            tr = self._tera()
            tmark = ("  ◈ Tera %s" % tr["active"] if tr.get("active") else
                     "  ◈ Tera ready (%s)" % tr["can"] if tr.get("can") else
                     "  (Tera used)" if (tr.get("used") and tr.get("allowed")) else "")
            foe_t = "  ◈ Tera %s" % tr["foe"] if tr.get("foe") else ""
            import html as _h
            self._mech_tip = self._mech_tips(dm, tr)

            def mark(key, colour, text):
                """A marker; underlined (hover for details) when it has a tooltip."""
                if not text:
                    return ""
                lead = "&nbsp;&nbsp;"
                body = _h.escape(text.strip())
                if key in self._mech_tip:
                    return lead + '<a href="%s" style="color:%s; text-decoration:underline;">%s</a>' % (key, colour, body)
                return lead + '<span style="color:%s;">%s</span>' % (colour, body)
            sp = lambda t: _h.escape(t).replace("  ", "&nbsp;&nbsp;")
            self.status.setText(
                sp("%s  %d/%d HP%s" % (p.name, p.hp, p.max_hp, _tags(p)))
                + mark("z", "#f4b400", zmark) + mark("d", "#a855f7", dmark) + mark("t", "#22d3ee", tmark)
                + "&nbsp;" * 8 + "vs" + "&nbsp;" * 8
                + sp("%s  %d/%d HP%s" % (l.name, l.hp, l.max_hp, _tags(l)))
                + mark("fd", "#a855f7", foe_d) + mark("ft", "#22d3ee", foe_t) + sp(aura))

        def roster(team):
            return "  ".join(
                ("<s>%s</s>" % c.name) if c.fainted else
                ("<b>%s</b> %d/%d%s" % (c.name, c.hp, c.max_hp, _tags(c, bench=True)))
                for c in team)
        self.party.setText("You: %s<br>%s: %s" % (
            roster(s.player_team), s.gym.leader, roster(s.leader_team)))

        self.mode_btn.setText("Mode: Auto  (click for Manual)" if self.auto
                              else "Mode: Manual  (click for Auto)")
        self._sync_move_buttons()

    def _sync_move_buttons(self):
        self._sync_move_texts()
        self._fit_move_buttons()

    def _fit_move_buttons(self):
        """Every move button wide enough for its whole label (Max Moves, Z-Moves
        and Tera Blast run long): the window grows to fit rather than cut text."""
        try:
            f = QFont(self.font())
            f.setBold(True)                    # the coloured labels are bold
            fm = QFontMetrics(f)
            for b in self.move_buttons:
                if not b.isHidden():
                    w = b.card_width() if getattr(b, "card_on", False) else 0
                    b.setMinimumWidth(w or fm.horizontalAdvance(b.text()) + 40)
            lay = self.layout()
            if lay is not None:
                lay.activate()
            need = self.minimumSizeHint().width()
            if self.width() < need:
                scr = self.screen()
                cap = scr.availableGeometry().width() - 40 if scr is not None else need
                self.resize(min(need, max(cap, 600)), self.height())
        except Exception:
            pass

    def _sync_move_texts(self):
        p = self.session.player_active
        atks = (p.attacks if p else []) or []
        self.moves_box.setVisible(not self.auto and not self.session.finished)

        # Out of PP on everything: the only option is Struggle, so say so
        # rather than showing four dead buttons.
        if p is not None and p.must_struggle():
            for i, b in enumerate(self.move_buttons):
                if i == 0:
                    b.setText("1.  STRUGGLE  (no PP left)")
                    b.setEnabled(not self.session.finished)
                    b.setVisible(True)
                else:
                    b.setVisible(False)
            return

        zmap = self._zmoves()
        self.z_btn.setVisible(bool(zmap) and not self.auto and not self.session.finished)
        if not zmap and self.z_btn.isChecked():
            self.z_btn.setChecked(False)
        z_on = bool(zmap) and self.z_btn.isChecked()
        dm = self._dmax()
        self.d_btn.setVisible(bool(dm.get("can")) and not self.auto and not self.session.finished)
        if not dm.get("can") and self.d_btn.isChecked():
            self.d_btn.setChecked(False)
        d_on = bool(dm.get("can")) and self.d_btn.isChecked()
        self.d_btn.setText("◆ Dynamax ON - pick a move" if d_on else "◆ Dynamax ready")
        tr = self._tera()
        self.t_btn.setVisible(bool(tr.get("can")) and not self.auto and not self.session.finished)
        if not tr.get("can") and self.t_btn.isChecked():
            self.t_btn.setChecked(False)
        t_on = bool(tr.get("can")) and self.t_btn.isChecked()
        self.t_btn.setText(("◈ Tera ON (%s) - pick a move" if t_on else "◈ Tera ready (%s)") % tr.get("can", ""))
        if (d_on or dm.get("active")) and not z_on:
            # Max Moves: preview (toggle on) or for real (Dynamaxed now), in purple
            maxes = {m.get("id"): m for m in (dm.get("moves") or [])}
            for i, b in enumerate(self.move_buttons):
                if i >= len(atks):
                    b.setVisible(False)
                    continue
                mv = atks[i]
                left, mx = p.pp_left(mv), p.max_pp.get(mv, 0)
                info = maxes.get(_mid(mv)) or {}
                name = info.get("name") or str(mv).replace("-", " ").title()
                b.setText("%d.  ◆ %s%s      PP %d/%d" % (i + 1, name, "  ·  Power %d" % info["power"]
                                                       if info.get("power") else "", left, mx))
                b.setStyleSheet("QPushButton { color:#a855f7; font-weight:bold; }")
                b.setToolTip(self._dtip(info))
                b.setEnabled(bool(left) and not self.session.finished)
                b.setVisible(True)
            return
        if t_on and not z_on:
            # Tera: the move you pick becomes Tera Blast (its Tera type) and is used now
            T = tr.get("can")
            for i, b in enumerate(self.move_buttons):
                if i >= len(atks):
                    b.setVisible(False)
                    continue
                mv = atks[i]
                b.setText("%d.  %s  \u2192  \u25c8 Tera Blast (%s)" % (i + 1, str(mv).replace("-", " ").title(), T))
                b.setStyleSheet("QPushButton { color:#22d3ee; font-weight:bold; }")
                b.setToolTip("<b>\u25c8 Tera Blast (%s)</b><br>%s becomes Tera Blast for the rest of the battle and "
                             "is used right away: a %s move, 80 power, using its stronger attacking stat."
                             % (T, str(mv).replace("-", " ").title(), T))
                b.setEnabled(not self.session.finished)
                b.setVisible(True)
            return
        for b in self.move_buttons:
            b.setStyleSheet("")
        self.z_btn.setText("✦ Z-Move ON - pick a move" if z_on else "✦ Z-Move ready")
        for i, b in enumerate(self.move_buttons):
            if i < len(atks):
                mv = atks[i]
                left, mx = p.pp_left(mv), p.max_pp.get(mv, 0)
                zname = zmap.get(_mid(mv)) if z_on else None
                if z_on:
                    b.setText("%d.  ✦ Z: %s%s" % (i + 1, zname, self._zpower(mv)) if zname else "%d.  -" % (i + 1))
                    b.setStyleSheet("QPushButton { color:#f4b400; font-weight:bold; }" if zname else "")
                    b.setToolTip(self._ztip(mv) if zname else "This move has no Z-Move with that crystal.")
                    b.setEnabled(bool(zname) and bool(left) and not self.session.finished)
                    b.setVisible(True)
                    continue
                zname = zmap.get(_mid(mv))
                # a card: type-coloured stripe, effectiveness against the foe out now, details
                b.set_card("%d. %s%s" % (i + 1, str(mv).replace("-", " ").title(), "  ✦" if zname else ""),
                           card_info(mv, self.session.leader_active, tr.get("foe")), "PP %d/%d" % (left, mx))
                try:
                    from ..pyobj.attack_dialog import move_tooltip
                    tip = move_tooltip(mv)
                except Exception:
                    tip = ""
                if zname:
                    tip = ("✦ Can become " + self._ztip(mv) + "<br>Click Z-Move first, then this move."
                           + ("<br><br><i>As a normal move:</i><br>" + tip if tip else ""))
                b.setToolTip(tip)
                if _mid(mv) == "terablast" and tr.get("active"):
                    T = tr["active"]
                    b.setText("%d.  \u25c8 Tera Blast (%s)      PP %d/%d" % (i + 1, T, left, mx))
                    b.setStyleSheet("QPushButton { color:#22d3ee; font-weight:bold; }")
                    b.setToolTip("<b>\u25c8 Tera Blast (%s)</b><br>A %s move, 80 power, using its stronger attacking "
                                 "stat." % (T, T))
                b.setEnabled(bool(left) and not self.session.finished)
                b.setVisible(True)
            else:
                # moves sealed in this fight (above the level it fights at): shown, not usable
                sealed = list((getattr(getattr(p, "source", None), "sealed_moves", None) or {}).items())
                j = i - len(atks)
                if j < len(sealed):
                    mv, lv = sealed[j]
                    info = dict(card_info(mv) or {"colour": "#888888", "details": ""}, kind=None,
                                tag="Sealed · Lv %d" % lv)
                    b.set_card(str(mv).replace("-", " ").title(), info, "")
                    b.setToolTip("Sealed in this fight: it unlocks once this Pokémon fights at Lv %d or higher."
                                 % lv)
                    b.setEnabled(False)
                    b.setVisible(True)
                else:
                    b.setVisible(False)

    # ------------------------------------------------------------- turns --
    def _use_move_index(self, n: int):
        p = self.session.player_active
        if p is None or self.session.finished:
            return
        if p.must_struggle():
            if n == 0:
                self._take_turn(None)      # run_turn forces Struggle
            return
        atks = p.attacks or []
        tera_pick = self.t_btn.isChecked() and bool(self._tera().get("can"))
        if n < len(atks) and (p.pp_left(atks[n]) > 0 or tera_pick):
            z = self.z_btn.isChecked() and bool(self._zmoves().get(_mid(atks[n])))
            d = (not z) and self.d_btn.isChecked() and bool(self._dmax().get("can"))
            t = (not z) and (not d) and self.t_btn.isChecked() and bool(self._tera().get("can"))
            for b in (self.z_btn, self.d_btn, self.t_btn):
                b.setChecked(False)
            self._take_turn(atks[n], z=z, dmax=d, tera=t)

    def _auto_tick(self):
        if self.session.finished:
            self._timer.stop()
            return
        self._take_turn(None)

    @staticmethod
    def _list(xs) -> str:
        xs = list(xs or [])
        return ", ".join(xs[:-1]) + " and " + xs[-1] if len(xs) > 1 else (xs[0] if xs else "nothing")

    def _mech_hover(self, link):
        """Hovering an underlined marker: its explanation, right at the cursor."""
        tip = self._mech_tip.get(link or "")
        if tip:
            QToolTip.showText(QCursor.pos(), tip, self.status)
        else:
            QToolTip.hideText()

    def _tera_text(self, tr) -> str:
        """What Terastallizing does for your Pokemon (ready or done)."""
        T, own, m = tr.get("type"), list(tr.get("types") or []), tr.get("matchups") or {}
        if not T:
            return ""
        name = tr.get("name") or "your Pokémon"
        bits = ["it defends as pure %s - weak to %s%s%s" % (
            T, self._list(m.get("weak")),
            "; resists %s" % self._list(m.get("resist")) if m.get("resist") else "",
            "; immune to %s" % self._list(m.get("immune")) if m.get("immune") else "")]
        if T in own:
            others = [t for t in own if t != T]
            bits.append("%s moves get double the same-type boost (2x instead of 1.5x)%s" % (
                T, "; its %s moves keep 1.5x" % "/".join(others) if others else ""))
        else:
            bits.append("%s moves gain the same-type boost (1.5x); its %s moves keep theirs" % (T, "/".join(own)))
        bits.append("weak %s moves hit with at least 60 power" % T)
        if tr.get("active"):
            bits.append("Tera Blast (%s) is a %s move, 80 power, using its stronger attacking stat" % (T, T))
        else:
            bits.append("the move you pick becomes Tera Blast (%s) and is used right away - a %s move, 80 power, "
                        "using its stronger attacking stat; it stays Tera Blast for the rest of the battle" % (T, T))
        import html as _h
        if tr.get("active"):
            head = "◈ %s is Terastallized (%s)" % (name, T)
        else:
            head = "◈ Tera ready - if %s Terastallizes into %s:" % (name, T)
        return ("<b>%s</b><br>" % _h.escape(head) + "<br>".join("• " + _h.escape(b[0].upper() + b[1:]) for b in bits)
                + "<br><i>Lasts the rest of the battle. Once per battle.</i>")

    def _mech_tips(self, dm, tr) -> dict:
        """Tooltips for the status-line markers (z, d, t, fd, ft): what each
        mechanic does right now. Only shown when hovered."""
        out = {}
        if self._zmoves():
            out["z"] = ("<b>✦ Z-Move ready</b><br>Once this battle, a move marked ✦ can become its Z-Move: "
                        "click Z-Move, then the move. Hover a ✦ move to see its Z-Move.")
        if dm.get("active"):
            out["d"] = ("<b>◆ Dynamaxed (%d turn%s left)</b><br>HP doubled; its moves are Max Moves - hover one "
                        "for its power and side effect." % (dm.get("turns", 0), "" if dm.get("turns") == 1 else "s"))
        elif dm.get("can"):
            out["d"] = ("<b>◆ Dynamax ready</b><br>For 3 turns your Pokémon's HP doubles and its moves become "
                        "Max Moves with side effects. Once per battle.")
        if dm.get("foe"):
            out["fd"] = "<b>◆ The foe is Dynamaxed</b><br>Its HP is doubled and it uses Max Moves for 3 turns."
        if tr.get("active") or tr.get("can"):
            out["t"] = self._tera_text(tr)
        if tr.get("foe"):
            fm = tr.get("foeMatchups") or {}
            out["ft"] = ("<b>◈ The foe's %s Terastallized into %s</b><br>It defends as pure %s - weak to %s%s." % (
                tr.get("foeName") or "Pokémon", tr["foe"], tr["foe"], self._list(fm.get("weak")),
                "; resists %s" % self._list(fm.get("resist")) if fm.get("resist") else ""))
        return out

    def _dmax(self) -> dict:
        """The Showdown helper's Dynamax view ({} on the classic engine)."""
        if self.session.finished:
            return {}
        return dict(getattr(self.session.engine, "dmax", None) or {})

    def _dmax_toggled(self, on):
        if on:                                    # one special move per turn
            for b in (self.z_btn, self.t_btn):
                if b.isChecked():
                    b.setChecked(False)
        self._sync_move_buttons()

    def _tera_toggled(self, on):
        if on:
            for b in (self.z_btn, self.d_btn):
                if b.isChecked():
                    b.setChecked(False)
        self._sync_move_buttons()

    def _tera(self) -> dict:
        """The Showdown helper's Tera view ({} on the classic engine)."""
        if self.session.finished:
            return {}
        return dict(getattr(self.session.engine, "tera", None) or {})

    @staticmethod
    def _dtip(info) -> str:
        """A Max Move: type, category, power and side effect."""
        if not info:
            return ""
        if info.get("category") == "Status":
            return "<b>%s</b> (Dynamax)<br>%s" % (info.get("name"), info.get("effect", ""))
        return ("<b>%s</b> (Dynamax)<br>%s  |  %s  |  Power %d<br>%s<br>"
                "From %s (Power %d)." % (info.get("name"), info.get("type"), info.get("category"),
                                        int(info.get("power") or 0), info.get("effect", ""),
                                        info.get("base"), int(info.get("basePower") or 0)))

    def _zinfo(self, mv) -> dict:
        return (getattr(self.session.engine, "zinfo", None) or {}).get(_mid(mv)) or {}

    def _zpower(self, mv) -> str:
        """'  ·  Power 100' for an attacking Z-Move ('' for a status one)."""
        z = self._zinfo(mv)
        return "  ·  Power %d" % z["power"] if z.get("power") else ""

    def _ztip(self, mv) -> str:
        """The Z-Move itself: type, category, power (or the status bonus)."""
        z = self._zinfo(mv)
        if not z:
            return ""
        if z.get("category") == "Status":
            return ("<b>%s</b> (Z-Move, once per battle)<br>%s" % (z.get("name"), z.get("effect", "")))
        return ("<b>%s</b> (Z-Move, once per battle)<br>%s  |  %s  |  Power %d<br>"
                "Replaces %s (Power %d) for this one move."
                % (z.get("name"), z.get("type"), z.get("category"), int(z.get("power") or 0),
                   z.get("base"), int(z.get("basePower") or 0)))

    def _zmoves(self):
        """{move id: Z-Move name} usable right now (Z-Ring owned), or {}."""
        sd = self.session.engine
        if self.session.finished or not getattr(sd, "zmoves", None) or getattr(sd, "zused", False):
            return {}
        try:
            from . import zmoves
            test = bool(getattr(self.session.gym, "is_test", False))     # Game > Test: no Ring needed
            return dict(sd.zmoves) if (zmoves.has_ring() or test) else {}
        except Exception:
            return {}

    def _take_turn(self, forced_move: Optional[str], z: bool = False, dmax: bool = False, tera: bool = False):
        try:
            from . import zmoves
            zf = zmoves.z_flag(z, self.auto, bool(getattr(self.session.gym, "is_test", False)))
        except Exception:
            zf = None
        try:
            from . import dmax as _dm
            df = _dm.dmax_flag(dmax, self.auto, bool(self._dmax().get("allowed")))
        except Exception:
            df = None
        try:
            from . import tera as _tr
            tf = _tr.tera_flag(tera, self.auto, bool(self._tera().get("allowed")))
        except Exception:
            tf = None
        events = GB.run_turn(self.session, forced_move=forced_move, z=zf, dmax=df, tera=tf)
        if events:
            # header + effects (boosts, status, screens, faints); cap for space
            self.log.setText("<br>".join(events[:12]))
        self.refresh()
        if self.session.finished:
            self._timer.stop()
            self._end()

    # ------------------------------------------------------------- modes --
    def _toggle_mode(self):
        self.auto = not self.auto
        if self.auto:
            self._timer.start()
        else:
            self._timer.stop()
        self.refresh()

    def _forfeit(self):
        if QMessageBox.question(
                self, "Forfeit",
                "Leave the gym? This counts as a loss and your team is healed."
        ) == QMessageBox.StandardButton.Yes:
            self.session.status = GymSession.LOST
            self._end()

    # --------------------------------------------------------------- end --
    def _end(self):
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        self._release()                 # BEFORE the callback, so wild mode is
        try:                            # already clean if anything below throws
            self.on_finish(self.session)
        finally:
            self.accept()

    def keyPressEvent(self, e):
        if not self.auto and not self.session.finished:
            k = e.key()
            for i, key in enumerate((Qt.Key.Key_1, Qt.Key.Key_2,
                                     Qt.Key.Key_3, Qt.Key.Key_4)):
                if k == key:
                    self._use_move_index(i)
                    return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        """Closing mid-fight forfeits. Team heals either way."""
        self._timer.stop()
        if not self.session.finished and not self._closing:
            self._closing = True
            self.session.status = GymSession.LOST
            self._release()
            try:
                self.on_finish(self.session)
            except Exception:
                pass
        self._release()
        super().closeEvent(e)
