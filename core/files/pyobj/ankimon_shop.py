import os
import random
from datetime import datetime
import json
from typing import Union

from aqt import mw
from aqt.qt import (
    Qt,
    QDialog,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QGridLayout,
    QFrame,
    QPixmap,
    QMessageBox,
    QSizePolicy,
    QFont,
    QFontDatabase,
    QToolTip,
    QScrollArea,
    QTimer,
    QWidget,
    QFontMetrics,
)
from aqt.theme import theme_manager

from ..functions.pokedex_functions import find_details_move

from ..utils import give_item, daily_item_list, get_item_price, get_item_description
from ..resources import items_path, user_path, pokemon_tm_learnset_path

# Daily Rotating Items Pool
DAILY_ITEMS_POOL = daily_item_list()


def _pool_here(n=0):
    """The shop's pool for the region you're in: evolution items only where they
    matter (wild_rules.item_drops_here)."""
    try:
        from ..wild import wild_rules as _wild
        pool = [i for i in DAILY_ITEMS_POOL if _wild.item_drops_here(i["name"])]
        return pool if len(pool) >= n else DAILY_ITEMS_POOL
    except Exception:
        return DAILY_ITEMS_POOL

# Standard Items
# Always in stock - heals and revives for Expeditions (no Poke Balls)
STANDARD_ITEMS = [{"name": n} for n in (
    "potion", "super-potion", "hyper-potion", "max-potion", "full-restore",
    "revive", "max-revive", "full-heal")]

# Sell Duplicate Items (user 2026-11-02): item categories that are never used up -
# evolution items, held items, plates, type boosters, gems, Tera Shards, Mega
# Stones, Z-Crystals, TMs, valuables. Potions, berries, balls, vitamins, X items
# and fossils are used up, so their spares are kept.
NEVER_USED_UP = {9, 10, 12, 13, 14, 15, 16, 17, 18, 19, 24, 36, 37, 42, 44, 45, 46, 52}
TM_CATEGORY = 37

# Row sizes at full scale. The Mart shrinks text, icons and buttons below these
# so every item fits the window (user 2026-11-02); it never grows past them.
ROW_H, ROW_GAP, ICON, NAME_PT, OWNED_PT, PRICE_PT = 84, 6, 56, 10, 7, 9
BTN_W, BTN_H, TITLE_PT, TITLE_H = 44, 30, 14, 40
MIN_SCALE = 0.35


def _item_name(item, is_tm=False):
    """What the player reads: 'Super Potion', 'Double-Edge'."""
    try:
        if is_tm:
            from ..move_names import format_move_name
            return format_move_name(item)
        from ..utils import item_display_name
        return item_display_name(item)
    except Exception:
        return str(item).replace("-", " ").title()


class _MartWindow(QDialog):
    """The Mart window: refits its rows to its size whenever it's resized."""

    def __init__(self, on_fit, parent=None):
        super().__init__(parent)
        self._on_fit = on_fit

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._on_fit()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._on_fit)


class PokemonShopManager:
    def __init__(self, logger, settings_obj, set_callback, get_callback):
        self.window = None
        self.logger = logger
        self.settings_obj = settings_obj
        self.set_callback = set_callback
        self.get_callback = get_callback
        self.number_of_daily_items = 3
        self.daily_items_reroll_cost = 100
        self.todays_daily_items = []
        self.todays_daily_tms = []

        # Retro Pokemon styling dimensions
        self.frame_h = 120
        self.frame_w = 340

        self.tm_price = 1000

        # Load Early GameBoy font
        self.early_gameboy_font = self._load_early_gameboy_font()

        self._rows = []         # one dict per item shown (widgets + item)
        self._sections = []     # (title label, item count)
        self._header = []       # (widget, base point size)
        self._scale = None
        self._hdr_need = None

    def _load_early_gameboy_font(self):
        """Load the Early GameBoy font for retro styling exclusively."""
        font = QFont("Early GameBoy", 14)
        return font

    def _font(self, points):
        f = QFont(self.early_gameboy_font)
        f.setPointSizeF(max(4.0, float(points)))
        return f

    def _is_night_mode(self):
        """Check if Anki is in night mode."""
        return theme_manager.night_mode

    def _get_theme_colors(self):
        """Get color scheme based on current theme using Anki's actual theme colors."""
        # Use Anki's built-in color variables that work with both themes
        if self._is_night_mode():
            return {
                "background": "var(--window-bg)",
                "border": "var(--border)",
                "text_primary": "var(--text)",
                "text_secondary": "var(--text-fg)",
                "accent_red": "#FD4F49",  # Red for Daily Items
                "accent_teal": "#1A99DD",  # Blue for Daily TMs
                "accent_yellow": "#84D437",  # Gray for Standard Items
                "button_bg": "var(--button-bg)",
                "button_hover": "var(--button-hover-bg)",
                "frame_bg": "var(--frame-bg)",
                "frame_hover": "var(--button-hover-bg)",
                "success": "#66BB6A",
                "warning": "#FF7043",
            }
        else:
            return {
                "background": "var(--window-bg)",
                "border": "var(--border)",
                "text_primary": "var(--text)",
                "text_secondary": "var(--text-fg)",
                "accent_red": "#FD4F49",  # Red for Daily Items
                "accent_teal": "#1A99DD",  # Blue for Daily TMs
                "accent_yellow": "#84D437",  # Gray for Standard Items
                "button_bg": "var(--button-bg)",
                "button_hover": "var(--button-hover-bg)",
                "frame_bg": "var(--frame-bg)",
                "frame_hover": "var(--button-hover-bg)",
                "success": "#4CAF50",
                "warning": "#FF6B6B",
            }

    def toggle_window(self):
        """Toggles the visibility of the Pokémon shop window."""
        if self.window and self.window.isVisible():
            self.window.close()
        else:
            if not self.window or not self.window.isVisible():
                self.create_gui()
            self.window.show()

    def create_gui(self):
        """Create the retro Pokémon-style shop GUI with theme support."""
        self._rows, self._sections, self._header, self._scale, self._hdr_need = [], [], [], None, None
        self.window = _MartWindow(self._fit, parent=mw)
        self.window.setWindowTitle("Ankimon Mart")
        self.window.setGeometry(100, 100, 1110, 580)
        try:                                   # the size you left it at (user 2026-11-02)
            from aqt.utils import restoreGeom, saveGeom
            restoreGeom(self.window, "ankimonMart")
            self.window.finished.connect(lambda *_: saveGeom(self.window, "ankimonMart"))
        except Exception:
            pass

        colors = self._get_theme_colors()

        # Apply Anki's theme class to inherit theme colors
        self.window.setProperty("class", "ankimon-shop")

        # Theme-aware background using Anki's CSS variables
        self.window.setStyleSheet(f"""
            QDialog {{
                background-color: {colors["background"]};
                border: 4px solid {colors["border"]};
            }}
        """)

        self.window.setWindowFlag(Qt.WindowType.Tool)

        # Main layout with Pokemon-style spacing
        main_layout = QVBoxLayout(self.window)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # Header section with theme-aware styling
        header_layout = self._create_header()
        main_layout.addLayout(header_layout)

        # Shop sections: in a frameless scroll area, so the window can be any size
        # (the rows shrink to fit; the scroll bar is only a last resort)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        body = QWidget()
        shop_layout = QHBoxLayout(body)
        shop_layout.setContentsMargins(0, 0, 0, 0)
        shop_layout.setSpacing(15)

        # Create the two shop sections with theme colors
        daily_section = self._create_shop_section(
            "Daily Items", self.get_daily_items(), colors["accent_red"]
        )
        tm_section = self._create_shop_section(
            "Daily TMs", self.get_daily_tms(), colors["accent_teal"], is_tm=True
        )
        standard_section = self._create_shop_section(
            "Always In Stock", [dict(i) for i in STANDARD_ITEMS], colors["accent_yellow"])

        shop_layout.addWidget(daily_section, 1)
        shop_layout.addWidget(tm_section, 1)
        shop_layout.addWidget(standard_section, 1)

        self._scroll.setWidget(body)
        main_layout.addWidget(self._scroll, 1)

    def _create_header(self):
        """Create the theme-aware Ankimon Mart header in a single horizontal line."""
        colors = self._get_theme_colors()
        header_layout = QHBoxLayout()
        header_layout.setSpacing(20)

        # Ankimon Mart title
        title_label = QLabel("ANKIMON MART")
        title_label.setFont(self._font(18))
        title_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {colors["text_primary"]};
                background-color: {colors["border"]};
                border: 3px solid {colors["text_primary"]};
                border-radius: 8px;
                padding: 8px 16px;
                margin: 4px;
            }}
        """)

        # Sell Duplicate Items (user 2026-11-02): spares of anything never used up
        sell_button = QPushButton("SELL DUPLICATE ITEMS")
        sell_button.setFont(self._font(10))
        sell_button.setMinimumHeight(50)
        sell_button.setToolTip("Sells the spares of items that are never used up (evolution items, "
                               "held items, TMs...) for half their price and keeps one of each. "
                               "Shows you the list first.")
        sell_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors["accent_teal"]};
                color: {colors["text_primary"]};
                border: 3px solid {colors["text_primary"]};
                border-radius: 8px;
                font-weight: bold;
                padding: 0 12px;
            }}
            QPushButton:hover {{
                background-color: {colors["button_hover"]};
                border: 3px solid {colors["accent_teal"]};
            }}
            QPushButton:pressed {{
                background-color: {colors["border"]};
            }}
        """)
        sell_button.clicked.connect(self.sell_duplicates)

        # Money display
        self.currency_qlabel = QLabel(
            f"MONEY: {self.settings_obj.get('trainer.cash')}¥"
        )
        self.currency_qlabel.setFont(self._font(12))
        self.currency_qlabel.setStyleSheet(f"""
            QLabel {{
                color: {colors["text_primary"]};
                background-color: {colors["button_bg"]};
                border: 2px solid {colors["text_primary"]};
                border-radius: 6px;
                padding: 6px 12px;
            }}
        """)

        # Create the reroll button with the desired text
        reroll_button = QPushButton(f"REROLL SHOP\n{self.daily_items_reroll_cost}¥")
        reroll_button.setFont(self._font(10))
        reroll_button.setMinimumHeight(50)

        reroll_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors["accent_red"]};
                color: {colors["text_primary"]};
                border: 3px solid {colors["text_primary"]};
                border-radius: 8px;
                font-weight: bold;
                padding: 0 12px;
            }}
            QPushButton:hover {{
                background-color: {colors["button_hover"]};
                border: 3px solid {colors["accent_yellow"]};
            }}
            QPushButton:pressed {{
                background-color: {colors["border"]};
            }}
        """)
        reroll_button.clicked.connect(
            lambda: self.reroll_daily_items(cost=self.daily_items_reroll_cost)
        )

        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(sell_button)
        header_layout.addStretch()
        header_layout.addWidget(self.currency_qlabel)
        header_layout.addWidget(reroll_button)

        self._header = [(title_label, 18), (sell_button, 10), (self.currency_qlabel, 12), (reroll_button, 10)]
        return header_layout

    def _create_shop_section(self, title, items, color, is_tm=False):
        """Create a theme-aware shop section without boundaries."""
        colors = self._get_theme_colors()
        section_frame = QFrame()
        section_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {colors["frame_bg"]};
                border-radius: 12px;
                margin: 4px;
            }}
        """)

        section_layout = QVBoxLayout(section_frame)
        section_layout.setContentsMargins(8, 8, 8, 8)
        section_layout.setSpacing(ROW_GAP)

        # Section title with Early GameBoy font
        title_label = QLabel(title.upper())
        title_label.setFont(self._font(TITLE_PT))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {colors["text_primary"]};
                background-color: {color};
                border-radius: 6px;
                padding: 6px;
                font-weight: bold;
            }}
        """)
        section_layout.addWidget(title_label)

        # Get items based on type
        if title == "Daily Items" and not self.todays_daily_items:
            self.todays_daily_items = items
        elif title == "Daily TMs" and not self.todays_daily_tms:
            self.todays_daily_tms = items

        for item in items:
            section_layout.addWidget(self._create_retro_item_frame(item, color, is_tm))

        section_layout.addStretch()
        self._sections.append((title_label, len(items)))
        return section_frame

    def _owned(self, name):
        try:
            return int((mw.ankimon_db.get_item(name) or {}).get("quantity") or 0)
        except Exception:
            return 0

    def _create_retro_item_frame(self, item, section_color, is_tm=False):
        """One item: its icon; name, Owned: N and price stacked (user 2026-11-02);
        a plain coloured button that buys one."""
        colors = self._get_theme_colors()

        if is_tm:
            item["UI_NAME"] = _item_name(item["name"], is_tm=True)
            item["price"] = self.tm_price
            # Description for TMs: fixed string
            description_text = (
                f"Allows a Pokémon to be taught the move {item['UI_NAME']} (if able)"
            )
        else:
            item["UI_NAME"] = _item_name(item["name"])
            item["price"] = get_item_price(item["name"])
            # Description for regular items: use get_item_description with language from settings
            description_text = get_item_description(
                item["name"], self.settings_obj.get("misc.language")
            )
            if not description_text:
                description_text = f"A useful item: {item['UI_NAME']}"

        frame = QFrame()
        frame.setFixedHeight(ROW_H)
        # Tooltip with item description for hover popup
        frame.setToolTip(description_text)

        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {colors["frame_bg"]};
                border-radius: 8px;
                margin: 2px;
            }}
            QFrame:hover {{
                background-color: {colors["frame_hover"]};
            }}
        """)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(10)

        # Item image
        image_label = QLabel()
        if is_tm:
            image_path = (
                items_path
                / f"Bag_TM_{(find_details_move(item['name']) or {}).get('type', 'Normal')}_SV_Sprite.png"
            )
        else:
            image_path = f"{items_path}/{item['name']}.png"
        pixmap = QPixmap(str(image_path))
        image_label.setPixmap(pixmap.scaled(ICON, ICON, Qt.AspectRatioMode.KeepAspectRatio))
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(image_label)

        # Item info: name / Owned: N / price
        info_layout = QVBoxLayout()
        info_layout.setSpacing(1)
        name_label = QLabel(item["UI_NAME"].upper())
        name_label.setStyleSheet(
            f"QLabel {{ color: {colors['text_secondary']}; font-weight: bold; }}"
        )
        owned_label = QLabel()
        owned_label.setStyleSheet(
            f"QLabel {{ color: {colors['text_secondary']}; font-weight: bold; }}"
        )
        price_label = QLabel(f"{item.get('price', 1000)}¥")
        name_label.setFont(self._font(NAME_PT))         # full size until the window is fitted
        owned_label.setFont(self._font(OWNED_PT))
        price_label.setFont(self._font(PRICE_PT))
        price_label.setStyleSheet(
            f"QLabel {{ color: {colors['success']}; font-weight: bold; }}"
        )
        info_layout.addStretch()
        info_layout.addWidget(name_label)
        info_layout.addWidget(owned_label)
        info_layout.addWidget(price_label)
        info_layout.addStretch()
        layout.addLayout(info_layout)
        layout.addStretch()

        # Buy button: no text - click it to buy one
        buy_button = QPushButton()
        buy_button.setFixedSize(BTN_W, BTN_H)
        buy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(buy_button)

        row = {"item": item, "is_tm": is_tm, "color": section_color, "frame": frame,
               "icon": image_label, "pixmap": pixmap, "name": name_label,
               "owned": owned_label, "price": price_label, "button": buy_button}
        buy_button.clicked.connect(lambda checked=False, row=row: self.buy_item(
            row["item"], "TM" if row["is_tm"] else None, row))
        self._rows.append(row)
        self._show_owned(row)
        return frame

    def _show_owned(self, row):
        """Owned: N under the name; a TM you have can't be bought again."""
        colors = self._get_theme_colors()
        n = self._owned(row["item"]["name"])
        row["owned"].setText(f"OWNED: {n}")
        button = row["button"]
        if row["is_tm"] and n > 0:
            button.setEnabled(False)
            button.setToolTip("You have this TM. TMs aren't used up.")
            button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors["frame_bg"]};
                    border: 2px solid {colors["border"]};
                    border-radius: 6px;
                }}
            """)
        else:
            button.setEnabled(True)
            button.setToolTip(f"Buy one for {row['item'].get('price')}¥")
            button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {row["color"]};
                    border: 2px solid {colors["text_primary"]};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background-color: {colors["button_hover"]};
                    border: 2px solid {row["color"]};
                }}
                QPushButton:pressed {{
                    background-color: {colors["border"]};
                }}
            """)

    def _fit(self):
        """Scale text, icons and buttons so every item fits the window: the longest
        column's rows share the height, the longest name sets the width."""
        try:
            if not self.window or not self._rows or not hasattr(self, "_scroll"):
                return
            vp = self._scroll.viewport()
            vw, vh = max(1, vp.width()), max(1, vp.height())
            longest = max((n for _t, n in self._sections), default=1) or 1
            s_h = (vh - 24) / float(TITLE_H + longest * (ROW_H + ROW_GAP))
            col_w = (vw - 2 * 15) / 3.0 - 28
            fm = QFontMetrics(self._font(NAME_PT))
            name_w = max(fm.horizontalAdvance(r["name"].text()) for r in self._rows)
            s_w = col_w / float(ICON + 20 + name_w + BTN_W)
            s = max(MIN_SCALE, min(1.0, s_h, s_w))
            # the header: as wide as the window allows (measured once, at full size)
            if self._hdr_need is None:
                self._hdr_need = sum(w.sizeHint().width() for w, _p in self._header) + 3 * 20
            hdr = max(0.5, min(1.0, (self.window.width() - 24) / float(max(1, self._hdr_need))))
            key = (round(s, 2), round(hdr, 2))
            if key == self._scale:
                return
            self._scale = key
            for w, pts in self._header:
                w.setFont(self._font(pts * hdr))
            tfm = QFontMetrics(self._font(TITLE_PT))
            for title, _n in self._sections:
                t = (col_w + 12) / float(max(1, tfm.horizontalAdvance(title.text()) + 16))
                title.setFont(self._font(TITLE_PT * min(1.0, t, max(s, 0.6))))
            icon = max(12, int(ICON * s))
            for r in self._rows:
                r["frame"].setFixedHeight(max(24, int(ROW_H * s)))
                r["name"].setFont(self._font(NAME_PT * s))
                r["owned"].setFont(self._font(OWNED_PT * s))
                r["price"].setFont(self._font(PRICE_PT * s))
                r["button"].setFixedSize(max(14, int(BTN_W * s)), max(10, int(BTN_H * s)))
                if not r["pixmap"].isNull():
                    r["icon"].setPixmap(r["pixmap"].scaled(
                        icon, icon, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.FastTransformation))
                r["icon"].setFixedWidth(icon)
        except Exception as e:
            try:
                self.logger.log("warning", f"Mart: could not fit the window: {e}")
            except Exception:
                pass

    def get_daily_items(self):
        """Generate daily items based on the current date."""
        db = mw.ankimon_db
        shop_data = db.get_user_data("todays_shop")
        if shop_data:
            if shop_data.get("items") and shop_data.get("date") == datetime.now().strftime("%Y-%m-%d"):
                sellable = {i["name"] for i in DAILY_ITEMS_POOL}      # today's list may predate a fix
                return [i for i in shop_data.get("items") if i.get("name") in sellable]

        seed = datetime.now().strftime("%Y-%m-%d")
        # a private RNG: seeding the global one made every random roll
        # (shinies, spawns...) repeat in the same order after opening the shop
        return random.Random(seed).sample(_pool_here(self.number_of_daily_items), self.number_of_daily_items)

    def get_daily_tms(self):
        """Works like get_daily_items, but for TMs"""
        db = mw.ankimon_db
        shop_data = db.get_user_data("todays_shop")
        if shop_data:
            if shop_data.get("technical_machines") and shop_data.get("date") == datetime.now().strftime("%Y-%m-%d"):
                return shop_data.get("technical_machines")

        tm_pool = self.get_tm_pool()
        seed = datetime.now().strftime("%Y-%m-%d")
        return random.Random(seed).sample(tm_pool, self.number_of_daily_items)

    def get_tm_pool(self) -> list[str]:
        with open(pokemon_tm_learnset_path, "r") as f:
            pokemon_tm_learnset = json.load(f)

        def flatten(xss):
            return [x for xs in xss for x in xs]

        all_tms = flatten(pokemon_tm_learnset.values())
        all_tms = set(all_tms)
        all_tms = list(
            {
                "name": tm,
                "description": f"Allows a Pokémon to be taught the move {tm} (if able).",
                "price": self.tm_price,
                "item_type": "TM",
            }
            for tm in all_tms
        )

        # Ensure deterministic order
        all_tms.sort(key=lambda tm: tm["name"])

        return all_tms

    def _warn(self, text):
        colors = self._get_theme_colors()
        msg = QMessageBox(self.window or mw)
        msg.setWindowTitle("Ankimon Mart")
        msg.setText(text)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStyleSheet(f"""
            QMessageBox {{
                background-color: {colors["background"]};
                color: {colors["text_primary"]};
            }}
            QMessageBox QPushButton {{
                background-color: {colors["warning"]};
                color: {colors["text_primary"]};
                border: 2px solid {colors["text_primary"]};
                border-radius: 4px;
                padding: 4px 8px;
                font-weight: bold;
            }}
        """)
        msg.exec()

    def _set_cash(self, value):
        self.set_callback("trainer.cash", int(value))
        self.currency_qlabel.setText(f"MONEY: {self.settings_obj.get('trainer.cash')}¥")

    def buy_item(self, item, item_type: Union[str, None] = None, row=None):
        """Buy one: the money and Owned: N update in place, with a short note
        instead of a pop-up (user 2026-11-02: click one to buy one)."""
        try:
            if not item.get("price"):          # no price: a reward, not for sale
                raise ValueError("this item isn't sold in the shop")
            if self.settings_obj.get("trainer.cash") < item["price"]:
                self._warn("You don't have enough money!")
                return
            self._set_cash(self.get_callback("trainer.cash") - item["price"])
            give_item(item["name"], item_type)
            if row is not None:
                self._show_owned(row)
            try:
                from aqt.utils import tooltip
                tooltip(f"Bought {item.get('UI_NAME', 'it')} for {item['price']}¥", parent=self.window)
            except Exception:
                pass
        except Exception as e:
            self.logger.log_and_showinfo("error", f"Failed to purchase item: {e}")

    def duplicates(self):
        """[(item name, label, spares, money each)] - the spares of items that are
        never used up, at half their price; one of each is kept. Items without a
        price (rewards) are kept too."""
        out = []
        for it in mw.ankimon_db.get_all_items() or []:
            n = int(it.get("quantity") or 0)
            cat = it.get("category_id")
            if n < 2 or cat not in NEVER_USED_UP:
                continue
            name = str(it.get("item_name") or "")
            tm = cat == TM_CATEGORY
            price = int(it.get("cost") or 0) or (self.tm_price if tm else int(get_item_price(name) or 0))
            if price // 2 <= 0 or not name:
                continue
            label = ("TM " if tm else "") + _item_name(name, is_tm=tm)
            out.append((name, label, n - 1, price // 2))
        return sorted(out, key=lambda x: x[1].lower())

    def sell_duplicates(self):
        """Sell Duplicate Items: lists the spares and their money, then sells them
        if you say so, keeping one of each."""
        try:
            dups = self.duplicates()
            if not dups:
                QMessageBox.information(self.window or mw, "Ankimon Mart",
                                        "No duplicates to sell. Items that get used up "
                                        "(potions, berries, balls...) are never counted.")
                return
            total = sum(k * each for _n, _l, k, each in dups)
            spares = sum(k for _n, _l, k, _e in dups)
            lines = [f"{label} x{k} - {k * each}¥" for _n, label, k, each in dups]
            box = QMessageBox(self.window or mw)
            box.setWindowTitle("Sell Duplicate Items")
            box.setIcon(QMessageBox.Icon.Question)
            box.setText(f"Sell {spares} spare item{'s' if spares != 1 else ''} for {total}¥? "
                        "You keep one of each.")
            box.setInformativeText("\n".join(lines[:20]) + (
                f"\n...and {len(lines) - 20} more" if len(lines) > 20 else ""))
            if len(lines) > 20:
                box.setDetailedText("\n".join(lines))
            sell = box.addButton("Sell", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not sell:
                return
            got = sold = 0
            for name, _label, k, each in dups:
                k = min(k, self._owned(name) - 1)        # the bag as it is now
                if k <= 0:
                    continue
                mw.ankimon_db.update_item_quantity(name, -k)
                got += k * each
                sold += k
            self._set_cash(self.get_callback("trainer.cash") + got)
            for row in self._rows:
                self._show_owned(row)
            try:
                from aqt.utils import tooltip
                tooltip(f"Sold {sold} spare item{'s' if sold != 1 else ''} for {got}¥", parent=self.window)
            except Exception:
                pass
        except Exception as e:
            self.logger.log_and_showinfo("error", f"Failed to sell duplicates: {e}")

    def reroll_daily_items(self, cost: int = 0) -> None:
        """Rerolls the daily items in the shop with theme-aware messaging"""
        if self.settings_obj.get("trainer.cash") < cost:
            self._warn("You don't have enough money to reroll!")
            return

        self._set_cash(self.get_callback("trainer.cash") - cost)

        # Generate new random items
        random.seed()  # Use current time for truly random reroll
        self.todays_daily_items = random.sample(
            _pool_here(self.number_of_daily_items), self.number_of_daily_items
        )
        self.todays_daily_tms = random.sample(
            self.get_tm_pool(), self.number_of_daily_items
        )

        # SAVE IMMEDIATELY - before GUI refresh
        data = {
            "items": self.todays_daily_items,
            "technical_machines": self.todays_daily_tms,
            "date": datetime.now().strftime("%Y-%m-%d"),
        }
        mw.ankimon_db.set_user_data("todays_shop", data)

        # Now refresh the window - it will load from the updated JSON file
        self.toggle_window()
        self.toggle_window()
