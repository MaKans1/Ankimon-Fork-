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
    QWidget, Qt, QTimer, QMessageBox,
)

from .gym_state import GymSession
from . import gym_battle as GB

AUTO_TURN_MS = 1100
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
            b = QPushButton("-")
            b.setMinimumHeight(34)
            b.clicked.connect(lambda _=False, n=i: self._use_move_index(n))
            grid.addWidget(b, i // 2, i % 2)
            self.move_buttons.append(b)
        root.addWidget(self.moves_box)

        foot = QHBoxLayout()
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
            self.status.setText(
                "%s  %d/%d HP%s        vs        %s  %d/%d HP%s"
                % (p.name, p.hp, p.max_hp, _tags(p), l.name, l.hp, l.max_hp, _tags(l)))

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

        for i, b in enumerate(self.move_buttons):
            if i < len(atks):
                mv = atks[i]
                left, mx = p.pp_left(mv), p.max_pp.get(mv, 0)
                b.setText("%d.  %s      PP %d/%d"
                          % (i + 1, str(mv).replace("-", " ").title(), left, mx))
                try:
                    from ..pyobj.attack_dialog import move_tooltip
                    b.setToolTip(move_tooltip(mv))
                except Exception:
                    b.setToolTip("")
                b.setEnabled(bool(left) and not self.session.finished)
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
        if n < len(atks) and p.pp_left(atks[n]) > 0:
            self._take_turn(atks[n])

    def _auto_tick(self):
        if self.session.finished:
            self._timer.stop()
            return
        self._take_turn(None)

    def _take_turn(self, forced_move: Optional[str]):
        events = GB.run_turn(self.session, forced_move=forced_move)
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
