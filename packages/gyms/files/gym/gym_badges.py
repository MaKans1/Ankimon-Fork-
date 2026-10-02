"""
gym_badges.py — the Gym Badge case.

DERIVED, NOT STORED
    Badges are not a separate record. Earned state is read straight from
    gym_progress.defeated, which is already written when you beat a leader.
    That means the case back-fills automatically: a gym beaten before this
    screen existed shows its badge the first time you open it, and adding new
    gyms later needs no migration.

SPRITES
    Drop a PNG named <gym_id>.png into:
        user_files/sprites/gym_badges/
    e.g. 1.png for the Boulder Badge. Anything missing falls back to a drawn
    placeholder, so the screen works before any art exists.

SCALING
    Everything iterates gym_data.GYMS. Appending a Gym(...) there — a gym 4,
    an Elite Four member, a Champion — makes a slot appear here with no code
    change.
"""

import os

from aqt import mw
from aqt.qt import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame, Qt, QPixmap,
)

from .gym_data import ladder, current_region, REGION_ORDER, LADDERS, badges_earned, badge_count
from .gym_state import GymProgress

BADGE_DIRNAME = "gym_badges"
SLOT = 96          # badge tile size


def badge_dir():
    """user_files/sprites/gym_badges, created on first use."""
    try:
        from ..resources import user_path_sprites
        d = os.path.join(str(user_path_sprites), BADGE_DIRNAME)
    except Exception:
        d = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "user_files", "sprites", BADGE_DIRNAME)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def badge_sprite_path(gym_id):
    """Where art for this gym goes. May not exist yet."""
    return os.path.join(badge_dir(), "%s.png" % gym_id)


def _placeholder(gym, earned):
    """A drawn stand-in until real art is dropped in. Earned badges show the
    gym number in colour; unearned are greyed and padlocked."""
    lab = QLabel()
    lab.setFixedSize(SLOT, SLOT)
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    if earned:
        lab.setText("<div style='font-size:30px;font-weight:700;'>%d</div>"
                    % (gym.gym_id % 100 or gym.gym_id))
        lab.setStyleSheet(
            "border:3px solid #d4a017; border-radius:%dpx;"
            "background:#3a3320; color:#f0c040;" % (SLOT // 2))
    else:
        lab.setText("<div style='font-size:26px;'>&#128274;</div>")
        lab.setStyleSheet(
            "border:2px dashed #555; border-radius:%dpx;"
            "background:#242424; color:#666;" % (SLOT // 2))
    return lab


def _badge_tile(gym, earned):
    box = QVBoxLayout()
    box.setAlignment(Qt.AlignmentFlag.AlignHCenter)

    art = badge_sprite_path(gym.gym_id)
    used_art = False
    if os.path.exists(art):
        pm = QPixmap(art)
        if not pm.isNull():
            lab = QLabel()
            lab.setFixedSize(SLOT, SLOT)
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab.setPixmap(pm.scaled(SLOT, SLOT,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
            if not earned:
                lab.setStyleSheet("opacity:0.3;")
                lab.setEnabled(False)
            box.addWidget(lab, alignment=Qt.AlignmentFlag.AlignHCenter)
            used_art = True
    if not used_art:
        box.addWidget(_placeholder(gym, earned),
                      alignment=Qt.AlignmentFlag.AlignHCenter)

    name = QLabel(gym.badge_name if earned else "? ? ?")
    name.setAlignment(Qt.AlignmentFlag.AlignCenter)
    name.setStyleSheet("font-weight:600;" if earned else "color:#777;")
    box.addWidget(name)

    who = QLabel("%s — %s" % (gym.leader, gym.type_theme) if earned
                 else gym.name)
    who.setAlignment(Qt.AlignmentFlag.AlignCenter)
    who.setStyleSheet("color:#9aa4b2; font-size:11px;")
    box.addWidget(who)

    holder = QWidget()
    holder.setLayout(box)
    holder.setFixedWidth(SLOT + 70)
    return holder


class GymBadgeWindow(QDialog):
    """Read-only badge case. Earned state comes from gym_progress."""

    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("Gym Badges")
        self.setMinimumSize(560, 420)
        self._build()

    def _defeated(self):
        try:
            return GymProgress(mw.ankimon_db).defeated_ids()
        except Exception:
            return set()

    def _build(self):
        root = QVBoxLayout(self)

        defeated = self._defeated()
        region = current_region()
        gyms = ladder(region)
        earned = sum(1 for g in gyms if g.gym_id in defeated)

        head = QLabel("<b>%s Badges</b> &nbsp; %d of %d earned"
                      % (region, earned, len(gyms)))
        head.setStyleSheet("font-size:15px;")
        root.addWidget(head)
        others = QLabel("  ·  ".join("%s %d/%d" % (r, badges_earned(defeated, r), badge_count(r))
                                    for r in REGION_ORDER if r in LADDERS))
        others.setWordWrap(True)
        others.setStyleSheet("font-size:11px;")
        root.addWidget(others)

        note = QLabel("Badges are read from your gym record, so anything you "
                      "have already beaten appears here automatically.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#9aa4b2; font-size:11px;")
        root.addWidget(note)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(line)

        grid = QGridLayout()
        grid.setSpacing(14)
        for i, gym in enumerate(gyms):
            grid.addWidget(_badge_tile(gym, gym.gym_id in defeated),
                           i // 4, i % 4)
        holder = QWidget()
        holder.setLayout(grid)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        root.addWidget(scroll)

        foot = QLabel("Add art as <code>%s</code> (named 1.png, 2.png …). "
                      "Missing files use the placeholder above."
                      % badge_dir())
        foot.setWordWrap(True)
        foot.setStyleSheet("color:#777; font-size:10px;")
        root.addWidget(foot)

        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        root.addLayout(row)


def open_badge_case():
    """Menu entry point."""
    try:
        GymBadgeWindow(mw).exec()
    except Exception as e:
        try:
            from ..singletons import logger
            logger.log("error", "[gym] badge case failed: %s" % e)
        except Exception:
            print("[gym] badge case failed: %s" % e)
