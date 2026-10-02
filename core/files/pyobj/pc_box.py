import json
import uuid
from typing import Any, Callable

from aqt import mw, gui_hooks
from aqt.qt import (
    Qt,
    QDialog,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QGridLayout,
    QPixmap,
)

from aqt.theme import theme_manager  # Check if light / dark mode in Anki

from PyQt6.QtWidgets import (
    QLineEdit,
    QComboBox,
    QCheckBox,
    QMenu,
    QWidget,
    QScrollArea,
    QFrame,
    QRadioButton,
    QButtonGroup,
)
from PyQt6.QtCore import QSize, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon, QFont, QAction, QMovie, QCloseEvent, QResizeEvent

from ..pyobj.pokemon_obj import PokemonObject
from ..pyobj.reviewer_obj import Reviewer_Manager
from ..pyobj.test_window import TestWindow
from ..pyobj.translator import Translator
from ..pyobj.collection_dialog import MainPokemon
from ..gui_classes.pokemon_details import PokemonCollectionDetails
from ..pyobj.InfoLogger import ShowInfoLogger

from ..pyobj.settings import Settings
from ..functions.friendship_evolution import evolution_readiness, current_time_label
from ..functions.sprite_functions import get_sprite_path
from ..utils import load_custom_font, get_tier_by_id
from ..resources import icon_path, items_path, csv_file_items_cost, poke_evo_path
from ..business import calculate_cp_from_dict


def format_item_name(item_name: str) -> str:
    return item_name.replace("-", " ").title()


def clear_layout(layout):
    """
    Recursively removes all widgets and nested layouts from a given layout.

    This function iterates through all items in the provided layout, removes
    each widget or sub-layout, and ensures proper deletion and memory cleanup.

    Args:
        layout (QLayout): The layout to be cleared. Can contain widgets and/or nested layouts.
    """
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout():
            clear_layout(item.layout())


class PokemonSlotButton(QPushButton):
    rightClicked = pyqtSignal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.rightClicked.emit()
        super().mouseReleaseEvent(event)


class ScaledMovieLabel(QLabel):
    def __init__(self, gif_path, width, height):
        super().__init__()
        self.target_width = width
        self.target_height = height
        self.movie = QMovie(gif_path)
        self.movie.frameChanged.connect(self.on_frame_changed)
        self.movie.start()
        self.setFixedSize(width, height)

    def on_frame_changed(self, frame_number):
        # Get current frame pixmap
        pixmap = self.movie.currentPixmap()

        # Scale pixmap to target size (keep aspect ratio if you want)
        scaled_pixmap = pixmap.scaled(
            self.target_width,
            self.target_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        self.setPixmap(scaled_pixmap)


class PokemonPC(QDialog):
    def __init__(
        self,
        logger: ShowInfoLogger,
        translator: Translator,
        reviewer_obj: Reviewer_Manager,
        test_window: TestWindow,
        settings: Settings,
        main_pokemon: PokemonObject,
        parent=mw,
    ):
        super().__init__(parent)

        self.logger = logger
        self.translator = translator
        self.reviewer_obj = reviewer_obj
        self.test_window = test_window
        self.settings = settings
        self.main_pokemon_function_callback = lambda _pokemon_data: MainPokemon(
            _pokemon_data, main_pokemon, logger, translator, reviewer_obj, test_window
        )

        self.n_cols = 5
        self.n_rows = 6
        self.current_box_idx = 0  # Index of current displayed box
        self.gif_in_collection = settings.get("gui.gif_in_collection")

        self.slot_size = 75  # Side length in pixels of a PC slot

        self.resize_timer = QTimer()
        self.resize_timer.setSingleShot(True)
        self.resize_timer.timeout.connect(
            self.on_resize_timeout
        )  # Debounce resize events to avoid excessive refreshes during window resizing

        self.main_layout = QHBoxLayout()  # Main horizontal layout for split panels
        self.details_layout = QVBoxLayout()  # Layout for details panel
        self.details_widget = QWidget()  # Widget to hold details
        self.pokemon_details_layout = None

        # Widgets for filtering and sorting
        self.search_edit = None
        self.type_combo = None
        self.generation_combo = None
        self.tier_combo = None
        self.filter_favorites = None
        self.filter_is_holding_item = None
        self.filter_shiny = None
        self.filter_can_evolve = None
        self.sort_by_id = None
        self.sort_by_name = None
        self.sort_by_level = None
        self.sort_by_friendship = None
        self.sort_by_date = None
        self.sort_group = None
        self.selected_sort_key = "Date"
        self.desc_sort = None  # Sort by descending order
        self.current_stats_tab_index = 0  # Remember selected tab (Stats/IV/EV)

        # Subscribe to theme change hook to update UI dynamically
        gui_hooks.theme_did_change.append(self.on_theme_change)

        self.ensure_data_integrity()  # Necessary for legacy reasons

        self.grid_container = None
        self.pokemon_grid = None
        self.curr_box_label = None
        self.time_label = None

        # Cached BFF (highest-friendship Pokémon). Recomputed only when the
        # underlying collection could have changed (open/show, catch, evolve,
        # trade, release, favorite toggle, held-item change), NOT on pure
        # layout re-renders (resize, pagination, filter changes, selection).
        self._bff_id = None
        self._bff_dirty = True

        self.create_gui()
        self.refresh_pokemon_grid()

    def showEvent(self, event):
        """Refresh the grid whenever the PC is (re)opened.

        Two things drift while the window is closed: friendship (battles/reviews)
        and the day/night clock (just elapsed time). A plain ``.show()`` doesn't
        rebuild the grid, so without this the header clock, the BFF heart, and the
        time-gated evolution badges would all display whatever was last rendered.
        Invalidate the cached BFF and re-render so the reopened view is current.
        """
        self._bff_dirty = True
        super().showEvent(event)
        self.refresh_pokemon_grid()

    def on_theme_change(self):
        """
        Callback function triggered when Anki's theme changes (light to dark or vice versa).
        Refreshes the GUI to apply the new theme settings.
        """
        # Theme change is cosmetic — no data change, so reuse the cached BFF.
        self.refresh_gui(recompute_bff=False)

    def create_gui(self):
        """
        Builds and sets up the main graphical user interface for displaying and managing Pokémon.

        This method initializes the GUI layout, including:
        - Navigation controls to switch between Pokémon storage boxes
        - A grid display for showing Pokémon in the current box
        - Filters and sorting options to refine the displayed Pokémon
        - Optional animated sprites or static images based on user settings
        - A right-hand details panel with flexible width

        The GUI components include:
        - Navigation buttons and current box label
        - A dynamically populated grid of Pokémon buttons with sprite icons
        - Filtering options (search by name, type, generation, tier, favorites)
        - Sorting options (by ID, name, level, ascending/descending)
        - A flexible-width details panel on the right

        All components are added to the main layout and displayed within a resizable window.

        Side Effects:
            - Modifies the instance's layout and widget properties.
            - Connects UI elements to their corresponding interaction handlers.
        """
        self.setWindowTitle("Pokémon PC")

        # Determine theme based on Anki's night mode
        is_dark_mode = theme_manager.night_mode  # Correctly checks Anki's theme

        # Define authentic Pokémon-themed color palettes
        if is_dark_mode:
            # Dark Mode
            background_color = "#003A70"
            text_color = "#E0E0E0"
            button_bg = "#3B4CCA"
            button_border = "#6A73D9"
            hover_color = "#6A73D9"
            favorite_color = "#B3A125"
            favorite_hover_color = "#AF8308"
            input_bg = "#002B5A"  # Slightly lighter than background for input fields
            slot_bg_color = "#002B5A"
        else:
            # Light Mode
            background_color = "#E6F3FF"
            text_color = "#003A70"
            button_bg = "#3D7DCA"
            button_border = "#003A70"
            hover_color = "#A8D8FF"
            favorite_color = "#FFDE00"
            favorite_hover_color = "#FFA600"
            input_bg = "#FFFFFF"  # White background for input fields
            slot_bg_color = "#CCE5FF"

        # Set stylesheet for the entire dialog, now correctly using all theme variables
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {background_color};
            }}
            QWidget {{
                color: {text_color};
            }}
            QPushButton {{
                background-color: {button_bg};
                border: 1px solid {button_border};
                border-radius: 5px;
                padding: 5px;
                color: {text_color};
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            QLineEdit, QComboBox {{
                background-color: {input_bg};
                border: 1px solid {button_border};
                border-radius: 3px;
                padding: 3px;
                color: {text_color};
            }}
            QLabel {{
                color: {text_color};
            }}
            QTabWidget {{
                background-color: transparent;
                border: none;
            }}
            QTabBar {{
                background: transparent;
                qproperty-drawBase: 0;
            }}
            QTabWidget::pane {{
                border: 1px solid {button_border};
                border-radius: 5px;
                background: transparent;
                padding: 3px;
            }}
            QTabBar::tab {{
                background: {button_bg};
                border: 1px solid {button_border};
                padding: 6px;
                color: {text_color};
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
                /* No bottom margin needed if background is unified */
            }}
            QTabBar::tab:selected {{
                background: {hover_color};
            }}
            QTabBar::tab:!selected {{
                margin-top: 2px;
            }}
        """)

        # Theme variables for building the grid
        self.theme_vars = {
            "button_border": button_border,
            "background_color": background_color,
            "slot_bg_color": slot_bg_color,
            "favorite_color": favorite_color,
            "favorite_hover_color": favorite_hover_color,
            "hover_color": hover_color,
        }

        # Clear existing layout if this is called via refresh_gui
        if self.layout():
            clear_layout(self.layout())
        else:
            self.setLayout(self.main_layout)
        pokemon_list = self.fetch_filtered_pokemon()
        max_box_idx = (len(pokemon_list) - 1) // (self.n_rows * self.n_cols)

        # Collection panel
        collection_layout = QVBoxLayout()
        collection_layout.setContentsMargins(20, 10, 20, 10)  # Consistent margins
        box_selector_layout = QHBoxLayout()
        box_selector_layout.setContentsMargins(0, 0, 0, 10)
        prev_box_button = QPushButton("◀")
        next_box_button = QPushButton("▶")
        prev_box_button.setFixedSize(70, 50)
        next_box_button.setFixedSize(70, 50)
        prev_box_button.setFont(QFont("System", 25))
        next_box_button.setFont(QFont("System", 25))
        # Max box idx is updated in refresh_pokemon_grid
        prev_box_button.clicked.connect(lambda: self.navigate_box(-1))
        next_box_button.clicked.connect(lambda: self.navigate_box(1))
        self.curr_box_label = QLabel(
            self.translator.translate(
                "pc_box_label",
                current=1,
                total=1,
            )
        )
        self.curr_box_label.setFixedSize(150, 50)
        self.curr_box_label.setFont(
            load_custom_font(20, int(self.settings.get("misc.language")))
        )
        self.curr_box_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.curr_box_label.setStyleSheet(
            f"border: 1px solid {button_border}; background-color: {background_color};"
        )

        # Day/night time indicator so players know the current evolution window.
        # Only relevant when the friendship/time feature is enabled (the master
        # toggle); hidden otherwise. refresh_pokemon_grid keeps it in sync.
        self.time_label = QLabel(current_time_label())
        self.time_label.setFixedHeight(50)
        self.time_label.setFont(
            load_custom_font(16, int(self.settings.get("misc.language")))
        )
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setStyleSheet(
            f"border: 1px solid {button_border}; background-color: {background_color}; padding: 0px 8px;"
        )
        if not self.settings.get("evolution.friendship_time_enabled", True):
            self.time_label.hide()

        box_selector_layout.addStretch(1)  # Push buttons to center
        box_selector_layout.addWidget(prev_box_button)
        box_selector_layout.addWidget(self.curr_box_label)
        box_selector_layout.addWidget(next_box_button)
        box_selector_layout.addStretch(1)  # Push buttons to center
        box_selector_layout.addWidget(self.time_label)
        collection_layout.addLayout(box_selector_layout)

        # Grid Container in a Scroll Area to allow window shrinking
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        self.scroll_area.setMinimumSize(200, 200)  # Minimum size required for shrinking
        # Enforce pagination by turning off scrollbars
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.grid_container = QWidget()
        self.grid_container.setStyleSheet("background: transparent;")
        self.pokemon_grid = QGridLayout(self.grid_container)
        self.pokemon_grid.setSpacing(5)
        self.pokemon_grid.setContentsMargins(0, 0, 0, 0)
        self.pokemon_grid.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setWidget(self.grid_container)

        collection_layout.addWidget(self.scroll_area, 1)
        self.setup_filters_layout(collection_layout)

        collection_widget = QWidget()
        collection_widget.setLayout(collection_layout)
        self.main_layout.addWidget(collection_widget, 1)

        self.setup_details_panel(background_color)

    def setup_filters_layout(self, parent_layout):
        """
        Build and attach filter/sort controls below the PC grid.

        The method preserves previous control state when rebuilding the GUI,
        reconnects all filter/sort signals, and appends the resulting layout
        to ``parent_layout``.

        Args:
            parent_layout (QLayout): Layout that receives the filter controls.
        """
        # Bottom part to filter the Pokémon displayed
        filters_layout = QGridLayout()
        # Name filtering
        prev_text = self.search_edit.text() if self.search_edit is not None else ""
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by name, nickname or type (e.g. fire) - Enter")
        self.search_edit.setText(prev_text)
        self.search_edit.returnPressed.connect(lambda: self.go_to_box(0))
        search_button = QPushButton("Search")
        search_button.clicked.connect(lambda: self.go_to_box(0))
        # Type filtering
        prev_idx = self.type_combo.currentIndex() if self.type_combo is not None else 0
        self.type_combo = QComboBox()
        self.type_combo.addItem("All types")
        self.type_combo.addItems(
            [
                "Normal",
                "Fire",
                "Water",
                "Electric",
                "Grass",
                "Ice",
                "Fighting",
                "Poison",
                "Ground",
                "Flying",
                "Psychic",
                "Bug",
                "Rock",
                "Ghost",
                "Dragon",
                "Dark",
                "Steel",
                "Fairy",
            ]
        )
        self.type_combo.setCurrentIndex(prev_idx)
        self.type_combo.currentIndexChanged.connect(lambda: self.go_to_box(0))
        # Generation filtering
        prev_idx = (
            self.generation_combo.currentIndex()
            if self.generation_combo is not None
            else 0
        )
        self.generation_combo = QComboBox()
        self.generation_combo.addItem("All gens")
        self.generation_combo.addItems([f"Gen {i}" for i in range(1, 10, 1)])
        self.generation_combo.setCurrentIndex(prev_idx)
        self.generation_combo.currentIndexChanged.connect(lambda: self.go_to_box(0))
        # Tier filtering
        prev_idx = self.tier_combo.currentIndex() if self.tier_combo is not None else 0
        self.tier_combo = QComboBox()
        self.tier_combo.addItem("All tiers")
        self.tier_combo.addItems(
            ["Normal", "Legendary", "Mythical", "Baby", "Ultra", "Fossil", "Starter"]
        )
        self.tier_combo.setCurrentIndex(prev_idx)
        self.tier_combo.currentIndexChanged.connect(lambda: self.go_to_box(0))
        # Sorting by favorites
        is_checked = (
            self.filter_favorites.isChecked()
            if self.filter_favorites is not None
            else False
        )
        self.filter_favorites = QCheckBox("Favorites")
        self.filter_favorites.setChecked(is_checked)
        self.filter_favorites.stateChanged.connect(lambda: self.go_to_box(0))
        # Filtering Pokemon who hold items
        is_checked = (
            self.filter_is_holding_item.isChecked()
            if self.filter_is_holding_item is not None
            else False
        )
        self.filter_is_holding_item = QCheckBox("Holds item")
        self.filter_is_holding_item.setChecked(is_checked)
        self.filter_is_holding_item.stateChanged.connect(lambda: self.go_to_box(0))
        # Shiny filter
        is_checked = (
            self.filter_shiny.isChecked() if self.filter_shiny is not None else False
        )
        self.filter_shiny = QCheckBox("Shiny")
        self.filter_shiny.setChecked(is_checked)
        self.filter_shiny.stateChanged.connect(lambda: self.go_to_box(0))
        # Can evolve: ready now by level or friendship, or with an evolution
        # item in the bag that it can use at its level
        is_checked = (
            self.filter_can_evolve.isChecked() if self.filter_can_evolve is not None else False
        )
        self.filter_can_evolve = QCheckBox("Can evolve")
        self.filter_can_evolve.setToolTip(
            "Pokémon that can evolve now: by level or friendship, or with an evolution item in your bag")
        self.filter_can_evolve.setChecked(is_checked)
        self.filter_can_evolve.stateChanged.connect(lambda: self.go_to_box(0))
        # Sorting options
        sort_label = QLabel("Sort by:")

        # Radio buttons for mutually exclusive sorting
        self.sort_group = QButtonGroup(self)
        self.sort_by_id = QRadioButton("ID")
        self.sort_by_name = QRadioButton("Name")
        self.sort_by_level = QRadioButton("Level")
        self.sort_by_cp = QRadioButton("CP")
        self.sort_by_iv = QRadioButton("IV")
        self.sort_by_ev = QRadioButton("EV")
        self.sort_by_friendship = QRadioButton("Friendship")
        self.sort_by_date = QRadioButton("Date")

        self.sort_group.addButton(self.sort_by_id)
        self.sort_group.addButton(self.sort_by_name)
        self.sort_group.addButton(self.sort_by_level)
        self.sort_group.addButton(self.sort_by_cp)
        self.sort_group.addButton(self.sort_by_iv)
        self.sort_group.addButton(self.sort_by_ev)
        self.sort_group.addButton(self.sort_by_friendship)
        self.sort_group.addButton(self.sort_by_date)

        if self.selected_sort_key == "ID":
            self.sort_by_id.setChecked(True)
        elif self.selected_sort_key == "Name":
            self.sort_by_name.setChecked(True)
        elif self.selected_sort_key == "Level":
            self.sort_by_level.setChecked(True)
        elif self.selected_sort_key == "CP":
            self.sort_by_cp.setChecked(True)
        elif self.selected_sort_key == "IV":
            self.sort_by_iv.setChecked(True)
        elif self.selected_sort_key == "EV":
            self.sort_by_ev.setChecked(True)
        elif self.selected_sort_key == "Friendship":
            self.sort_by_friendship.setChecked(True)
        else:  # Date is the default
            self.sort_by_date.setChecked(True)

        # Connect signals
        self.sort_group.buttonClicked.connect(self.on_sort_button_clicked)

        sort_radio_layout = QHBoxLayout()
        sort_radio_layout.addWidget(sort_label)
        sort_radio_layout.addWidget(self.sort_by_id)
        sort_radio_layout.addWidget(self.sort_by_name)
        sort_radio_layout.addWidget(self.sort_by_level)
        sort_radio_layout.addWidget(self.sort_by_cp)
        sort_radio_layout.addWidget(self.sort_by_iv)
        sort_radio_layout.addWidget(self.sort_by_ev)
        sort_radio_layout.addWidget(self.sort_by_friendship)
        sort_radio_layout.addWidget(self.sort_by_date)
        sort_radio_widget = QWidget()
        sort_radio_widget.setLayout(sort_radio_layout)

        # Checkboxes for other options
        is_checked = self.desc_sort.isChecked() if self.desc_sort is not None else False
        self.desc_sort = QCheckBox("Descending")
        self.desc_sort.setChecked(is_checked)
        self.desc_sort.stateChanged.connect(lambda: self.go_to_box(0))

        # Adding the widgets to the layout
        filters_layout.addWidget(self.search_edit, 0, 0, 1, 4)
        filters_layout.addWidget(search_button, 0, 4, 1, 1)
        filters_layout.addWidget(self.type_combo, 1, 0, 1, 2)
        filters_layout.addWidget(self.generation_combo, 1, 2, 1, 2)
        filters_layout.addWidget(self.tier_combo, 1, 4, 1, 1)

        checkboxes_layout = QHBoxLayout()
        checkboxes_layout.addWidget(self.filter_favorites)
        checkboxes_layout.addWidget(self.filter_is_holding_item)
        checkboxes_layout.addWidget(self.filter_shiny)
        checkboxes_layout.addWidget(self.filter_can_evolve)
        checkboxes_layout.addWidget(self.desc_sort)  # Moved here
        checkboxes_widget = QWidget()
        checkboxes_widget.setLayout(checkboxes_layout)

        filters_layout.addWidget(checkboxes_widget, 2, 0, 1, 5)
        filters_layout.addWidget(sort_radio_widget, 3, 0, 1, 5)
        parent_layout.addLayout(filters_layout)

    def setup_details_panel(self, background_color):
        if self.pokemon_details_layout is not None:
            self.details_widget = QWidget()
            self.details_widget.setLayout(self.pokemon_details_layout)
            self.details_widget.setMinimumWidth(470)  # Ensure it's visible
            self.details_widget.setStyleSheet(f"background-color: {background_color};")
            self.main_layout.addWidget(self.details_widget, 2)
        else:
            # Ensure the panel is collapsed if no pokemon is selected
            self.details_widget = QWidget()
            self.details_widget.hide()
            self.main_layout.addWidget(self.details_widget, 0)

    def refresh_pokemon_grid(self, recompute_bff: bool = True):
        """
        Clears and rebuilds the grid.

        Args:
            recompute_bff (bool): When ``True`` (the default, used by every
                external data-mutating caller — catch, evolve, trade, release,
                fossil, main-pick), the BFF is recomputed via SQL. Pure layout
                re-renders (resize, pagination, filter changes, selection) pass
                ``False`` so the cached BFF is reused, avoiding the per-render
                ``json_extract`` query. A pending dirty flag forces a recompute
                regardless (e.g. after the window is shown).
        """
        if self.pokemon_grid is None:
            return

        clear_layout(self.pokemon_grid)
        self.gif_in_collection = self.settings.get("gui.gif_in_collection")
        # The day/night clock and the friendship-specific evolution badges are
        # part of the friendship/time feature, which is behind a master toggle.
        friendship_time_enabled = self.settings.get(
            "evolution.friendship_time_enabled", True
        )

        pokemon_list = self.fetch_filtered_pokemon()
        max_box_idx = max(0, (len(pokemon_list) - 1) // (self.n_rows * self.n_cols))

        if self.current_box_idx > max_box_idx:
            self.current_box_idx = max_box_idx

        if self.curr_box_label:
            self.curr_box_label.setText(
                self.translator.translate(
                    "pc_box_label",
                    current=self.current_box_idx + 1,
                    total=max_box_idx + 1,
                )
            )

        # Keep the day/night indicator current on every render, but only when
        # the friendship/time feature is enabled — otherwise hide it.
        if self.time_label is not None:
            if friendship_time_enabled:
                self.time_label.setText(current_time_label())
                self.time_label.show()
            else:
                self.time_label.hide()

        # Resolve the BFF (highest-friendship Pokémon). Recompute only when the
        # caller signals a possible data change or a prior invalidation is
        # pending; otherwise reuse the cached value so plain re-renders
        # (resize/pagination/filter/selection) skip the SQL query.
        if recompute_bff or self._bff_dirty:
            self._bff_id = self._compute_bff_id()
            self._bff_dirty = False
        bff_id = self._bff_id

        start_index = self.current_box_idx * self.n_rows * self.n_cols
        pokemon_list_slice = pokemon_list[
            start_index : start_index + self.n_rows * self.n_cols
        ]

        theme_vars = self.theme_vars
        border = theme_vars["button_border"]

        for row in range(self.n_rows):
            for col in range(self.n_cols):
                pokemon_idx = row * self.n_cols + col
                if pokemon_idx >= len(pokemon_list_slice):
                    empty_label = QLabel()
                    empty_label.setFixedSize(self.slot_size, self.slot_size)
                    self.pokemon_grid.addWidget(
                        empty_label, row, col, alignment=Qt.AlignmentFlag.AlignCenter
                    )
                    continue

                pokemon = pokemon_list_slice[pokemon_idx]
                pkmn_image_path = get_sprite_path(
                    "front",
                    "gif" if self.gif_in_collection else "png",
                    pokemon["id"],
                    pokemon.get("shiny", False),
                    pokemon["gender"],
                )
                pokemon_button = PokemonSlotButton("")
                pokemon_button.setFixedSize(self.slot_size, self.slot_size)

                # BFF (highest friendship) takes visual precedence over Favorite.
                is_bff = (
                    bff_id is not None
                    and pokemon.get("individual_id") == bff_id
                )
                if is_bff:
                    bg = "#FF69B4"  # Hot pink
                    h_bg = "#FF8DC7"
                elif pokemon.get("is_favorite"):
                    bg = theme_vars["favorite_color"]
                    h_bg = theme_vars["favorite_hover_color"]
                else:
                    bg = theme_vars["slot_bg_color"]
                    h_bg = theme_vars["hover_color"]
                pokemon_button.setStyleSheet(
                    f"QPushButton {{ background-color: {bg}; border: 1px solid {border}; border-radius: 5px; }} QPushButton:hover {{ background-color: {h_bg}; }}"
                )

                # Connect signals
                # Left click: Show details
                pokemon_button.clicked.connect(
                    lambda checked, pkmn=pokemon: self.show_pokemon_details(pkmn)
                )
                # Right click: Show actions menu
                pokemon_button.rightClicked.connect(
                    lambda pb=pokemon_button, pkmn=pokemon: self.show_actions_submenu(
                        pb, pkmn
                    )
                )
                self.pokemon_grid.addWidget(
                    pokemon_button, row, col, alignment=Qt.AlignmentFlag.AlignCenter
                )

                if self.gif_in_collection:
                    scaled_movie_label = ScaledMovieLabel(
                        pkmn_image_path, self.slot_size - 10, self.slot_size - 10
                    )
                    scaled_movie_label.setAttribute(
                        Qt.WidgetAttribute.WA_TransparentForMouseEvents
                    )
                    self.pokemon_grid.addWidget(
                        scaled_movie_label,
                        row,
                        col,
                        alignment=Qt.AlignmentFlag.AlignCenter,
                    )
                else:
                    pokemon_button.setIcon(QIcon(pkmn_image_path))
                    pokemon_button.setIconSize(
                        QSize(self.slot_size - 10, self.slot_size - 10)
                    )

                # Collect badge meanings so the same info is reachable on hover.
                # The badge QLabels below are WA_TransparentForMouseEvents (so the
                # slot stays clickable), which means *their* tooltips never fire —
                # we mirror the explanation onto the slot button, which does
                # receive hover events.
                badge_tooltips = []

                # Badge overlays, added last so they paint on top of the sprite.
                # Heart on the BFF slot (top-left corner).
                if is_bff:
                    heart_badge = QLabel("💖")
                    heart_badge.setAttribute(
                        Qt.WidgetAttribute.WA_TransparentForMouseEvents
                    )
                    heart_badge.setStyleSheet("background: transparent;")
                    self.pokemon_grid.addWidget(
                        heart_badge,
                        row,
                        col,
                        alignment=Qt.AlignmentFlag.AlignTop
                        | Qt.AlignmentFlag.AlignLeft,
                    )
                    badge_tooltips.append("💖 Your best friend (highest friendship)")

                # Sparkle on Pokémon ready to evolve (friendship or level-up) —
                # top-right. The level-up case mostly surfaces rejected/Everstone/
                # caught-high mons (a plain level-ready mon auto-evolves on level
                # up). The 🌙/☀️ wait badge below stays friendship-only because
                # required_time is None for level evolutions.
                readiness = evolution_readiness(
                    {
                        "id": pokemon["id"],
                        "friendship": pokemon.get("friendship", 0),
                        "everstone": pokemon.get("everstone", False),
                        "evolution_rejected": pokemon.get("evolution_rejected", False),
                        "level": pokemon.get("level", 1),
                    }
                )
                # Friendship/time evolution is behind a master toggle; its badges
                # only show when enabled. Level-up evolution is base-game and
                # always shows its ✨ badge.
                if readiness["ready"] and (
                    readiness["method"] == "level" or friendship_time_enabled
                ):
                    evo_badge = QLabel("✨")
                    evo_badge.setAttribute(
                        Qt.WidgetAttribute.WA_TransparentForMouseEvents
                    )
                    evo_badge.setStyleSheet("background: transparent;")
                    evo_badge.setToolTip(readiness["status_text"])
                    self.pokemon_grid.addWidget(
                        evo_badge,
                        row,
                        col,
                        alignment=Qt.AlignmentFlag.AlignTop
                        | Qt.AlignmentFlag.AlignRight,
                    )
                    badge_tooltips.append(f"✨ {readiness['status_text']}")
                elif (
                    friendship_time_enabled
                    and readiness["evolvable"]
                    and readiness["friendship_remaining"] == 0
                    and not readiness["time_ok"]
                    and readiness["required_time"]
                ):
                    # Friendship requirement is met — only the time of day is
                    # blocking. Show a sun/moon so the player knows to come back
                    # during the day / at night (full text is in the details
                    # panel and the day/night label at the top of the PC).
                    wait_icon = (
                        "🌙" if readiness["required_time"] == "night" else "☀️"
                    )
                    wait_badge = QLabel(wait_icon)
                    wait_badge.setAttribute(
                        Qt.WidgetAttribute.WA_TransparentForMouseEvents
                    )
                    wait_badge.setStyleSheet("background: transparent;")
                    wait_badge.setToolTip(readiness["status_text"])
                    self.pokemon_grid.addWidget(
                        wait_badge,
                        row,
                        col,
                        alignment=Qt.AlignmentFlag.AlignTop
                        | Qt.AlignmentFlag.AlignRight,
                    )
                    badge_tooltips.append(f"{wait_icon} {readiness['status_text']}")

                # Mirror the badge meaning(s) onto the (hover-capable) slot button
                # so the otherwise-unreachable badge tooltips become discoverable.
                if badge_tooltips:
                    pokemon_button.setToolTip("\n".join(badge_tooltips))

    def _compute_bff_id(self):
        """Return the individual_id of the highest-friendship Pokémon.

        The BFF is computed (not stored): the single Pokémon with the highest
        friendship across the whole collection, ignoring any with friendship 0.
        Ties are broken deterministically by ``rowid`` (oldest wins). Returns
        ``None`` if every Pokémon has 0 friendship or on query failure.
        """
        try:
            cursor = mw.ankimon_db.execute(
                "SELECT individual_id FROM captured_pokemon "
                "WHERE CAST(json_extract(data, '$.friendship') AS INTEGER) > 0 "
                "ORDER BY CAST(json_extract(data, '$.friendship') AS INTEGER) DESC, "
                "rowid ASC LIMIT 1"
            )
            row = cursor.fetchone()
            return row["individual_id"] if row else None
        except Exception as e:
            if self.logger:
                self.logger.log("error", f"Error computing BFF: {e}")
            return None

    def navigate_box(self, delta):
        """
        Move to a different box relative to the current one.

        Applies active filters to compute the valid page range and then
        navigates with wrap-around behavior.

        Args:
            delta (int): Relative box movement (for example ``-1`` or ``+1``).
        """
        pokemon_list = self.fetch_filtered_pokemon()
        max_idx = max(0, (len(pokemon_list) - 1) // (self.n_rows * self.n_cols))
        self.looparound_go_to_box(self.current_box_idx + delta, max_idx)

    def resizeEvent(self, event: QResizeEvent):
        """
        Triggered when the dialog is resized.
        Uses a timer to debounce the GUI refresh.
        """
        super().resizeEvent(event)
        self.resize_timer.start(200)

    def on_resize_timeout(self):
        """
        Recalculates dimensions and refreshes the grid if they have changed.
        Ensures the current box index remains valid for the new grid capacity.
        """
        new_cols, new_rows = self.calculate_grid_dimensions()
        if new_cols != self.n_cols or new_rows != self.n_rows:
            self.n_cols = new_cols
            self.n_rows = new_rows
            # Resize is pure layout — reuse the cached BFF.
            self.refresh_pokemon_grid(recompute_bff=False)

    def calculate_grid_dimensions(self):
        """
        Calculates how many columns and rows of slots fit in the current viewport.
        Ensures only fully visible slots are displayed by using scroll_area dimensions.
        """
        vw = self.scroll_area.viewport().width()
        vh = self.scroll_area.viewport().height()

        slot = self.slot_size
        spacing = 5
        new_cols = max(1, (vw + spacing) // (slot + spacing))
        new_rows = max(1, (vh + spacing) // (slot + spacing))

        return int(new_cols), int(new_rows)

    def refresh_gui(self, recompute_bff: bool = True):
        """
        Refreshes the entire graphical user interface by rebuilding its structure
        and then populating the grid.

        Args:
            recompute_bff (bool): Forwarded to :meth:`refresh_pokemon_grid`.
                Defaults to ``True`` because the data-mutating callers
                (favorite toggle, give/remove item, release/trade/rename/evolve
                via ``refresh_callback``) need a fresh BFF. Non-mutating callers
                (theme change, selecting a Pokémon) pass ``False``.
        """
        self.create_gui()
        self.refresh_pokemon_grid(recompute_bff=recompute_bff)
        self.layout().invalidate()
        self.layout().activate()

    def go_to_box(self, idx: int):
        """
        Navigates to the specified Pokémon storage box and updates the GUI accordingly.

        Args:
            idx (int): The index of the box to navigate to.

        Side Effects:
            - Updates the current box index.
            - Refreshes the Pokémon grid to display the selected box's contents.
        """
        self.current_box_idx = idx
        # Pagination and filter changes route through here; neither alters which
        # Pokémon is the BFF (it spans the whole collection), so reuse the cache.
        self.refresh_pokemon_grid(recompute_bff=False)

    def looparound_go_to_box(self, idx: int, max_idx: int):
        """
        Navigates to a box index with wrap-around behavior.

        If the provided index is less than 0, wraps around to the maximum index.
        If the index exceeds the maximum, wraps around to 0.
        Then updates the GUI to show the selected box.

        Args:
            idx (int): The target box index to navigate to.
            max_idx (int): The maximum valid box index.

        Side Effects:
            - Updates the current box index with wrapping.
            - Triggers a GUI refresh to display the selected box.
        """
        if idx < 0:
            idx = max_idx
        elif idx > max_idx:
            idx = 0
        self.go_to_box(idx)

    def adjust_pixmap_size(self, pixmap, max_width, max_height):
        """
        Scales a QPixmap to fit within the specified maximum width and height while maintaining aspect ratio.

        If the pixmap's width exceeds `max_width`, it is scaled down proportionally.
        Note: This implementation currently only scales based on width and does not consider `max_height`.

        Args:
            pixmap (QPixmap): The original pixmap to be resized.
            max_width (int): The maximum allowed width.
            max_height (int): The maximum allowed height (currently unused).

        Returns:
            QPixmap: The scaled pixmap, or the original if no scaling was needed.
        """
        original_width = pixmap.width()
        original_height = pixmap.height()

        if original_width > max_width:
            new_width = max_width
            new_height = (original_height * max_width) // original_width
            pixmap = pixmap.scaled(new_width, new_height)

        return pixmap

    def fetch_filtered_pokemon(self) -> list:
        """Dynamically builds a SQL query to filter and sort Pokémon, fetching only the lightweight stub data needed for the grid."""
        # Base query mapping direct virtual columns where available
        query_parts = [
            "SELECT individual_id, name, level, pokedex_id as id, shiny as shiny, "
            "rowid as original_index, json_extract(data, '$.nickname') as nickname, "
            "json_extract(data, '$.gender') as gender, json_extract(data, '$.is_favorite') as is_favorite, "
            "json_extract(data, '$.held_item') as held_item, "
            "json_extract(data, '$.friendship') as friendship, "
            "json_extract(data, '$.everstone') as everstone, "
            "json_extract(data, '$.evolution_rejected') as evolution_rejected, "
            "json_extract(data, '$.iv') as iv_json, json_extract(data, '$.ev') as ev_json "
            "FROM captured_pokemon WHERE 1=1"
        ]
        params = []

        # Name / Nickname filtering
        # Name / nickname / type words (functions/poke_search): "fire" lists
        # every Fire type, "fire char" Fire types whose name has "char".
        if self.search_edit is not None and self.search_edit.text():
            from ..functions import poke_search as PS
            _frag, _params = PS.sql_filter(self.search_edit.text())
            if _frag:
                query_parts.append(_frag)
                params.extend(_params)

        # Type filtering
        if self.type_combo is not None and self.type_combo.currentIndex() != 0:
            type_text = f"%{self.type_combo.currentText()}%"
            query_parts.append("AND json_extract(data, '$.type') LIKE ?")
            params.append(type_text)

        # Tier filtering
        if self.tier_combo is not None and self.tier_combo.currentIndex() != 0:
            query_parts.append("AND json_extract(data, '$.tier') = ?")
            params.append(self.tier_combo.currentText())

        # Favorites filtering
        if self.filter_favorites is not None and self.filter_favorites.isChecked():
            query_parts.append("AND json_extract(data, '$.is_favorite') = 1")

        # Held item filtering
        if self.filter_is_holding_item is not None and self.filter_is_holding_item.isChecked():
            query_parts.append("AND json_extract(data, '$.held_item') IS NOT NULL")

        # Shiny filtering
        if self.filter_shiny is not None and self.filter_shiny.isChecked():
            query_parts.append("AND shiny = 1")

        # Generation filtering
        if self.generation_combo is not None:
            gen_idx = self.generation_combo.currentIndex()
            if gen_idx != 0:
                gen_ranges = {
                    1: (1, 151),
                    2: (152, 251),
                    3: (252, 386),
                    4: (387, 493),
                    5: (494, 649),
                    6: (650, 721),
                    7: (722, 809),
                    8: (810, 905),
                    9: (906, 1025)
                }
                if gen_idx in gen_ranges:
                    start_id, end_id = gen_ranges[gen_idx]
                    query_parts.append("AND pokedex_id BETWEEN ? AND ?")
                    params.extend([start_id, end_id])

        # Sorting
        sort_key_str = self.selected_sort_key.lower() if hasattr(self, 'selected_sort_key') else "date"
        reverse = self.desc_sort is not None and self.desc_sort.isChecked()
        direction = "DESC" if reverse else "ASC"

        # A type word in the search lists that type A-Z (only overrides the
        # default "date" sort, never a sort you picked).
        if (sort_key_str == "date" and self.search_edit is not None
                and self.search_edit.text()):
            from ..functions import poke_search as PS
            if PS.has_type_term(self.search_edit.text()):
                sort_key_str = "name"

        if sort_key_str == "date":
            order_clause = f"ORDER BY original_index {direction}"
        elif sort_key_str == "name":
            order_clause = (f"ORDER BY name COLLATE NOCASE {direction}, "
                            f"json_extract(data, '$.nickname') COLLATE NOCASE {direction}, level DESC, original_index")
        elif sort_key_str == "level":
            order_clause = f"ORDER BY level {direction}, pokedex_id, original_index"
        elif sort_key_str == "id":
            order_clause = f"ORDER BY pokedex_id {direction}, level DESC, original_index"
        elif sort_key_str == "cp":
            order_clause = f"ORDER BY CAST(json_extract(data, '$.cp') AS REAL) {direction}, original_index"
        elif sort_key_str == "friendship":
            # COALESCE so a missing/NULL friendship sorts as 0 (grouped with the
            # zero-friendship Pokémon) instead of NULL drifting to an extreme
            # end of the list under ASC/DESC.
            order_clause = f"ORDER BY CAST(COALESCE(json_extract(data, '$.friendship'), 0) AS INTEGER) {direction}, original_index"
        else:
            # For IV/EV or default, sort by original_index first, then override in Python if needed
            order_clause = f"ORDER BY original_index {direction}"

        query = " ".join(query_parts) + " " + order_clause

        try:
            cursor = mw.ankimon_db.execute(query, tuple(params))
            results = []
            for row in cursor.fetchall():
                p = {
                    "original_index": row["original_index"],
                    "individual_id": row["individual_id"],
                    "id": row["id"],
                    "name": row["name"],
                    "nickname": row["nickname"],
                    "shiny": bool(row["shiny"]),
                    "level": row["level"],
                    "gender": row["gender"],
                    "is_favorite": bool(row["is_favorite"]),
                    "held_item": row["held_item"],
                    "friendship": row["friendship"] or 0,
                    "everstone": bool(row["everstone"]),
                    "evolution_rejected": bool(row["evolution_rejected"]),
                }

                # Pre-calculate sums for sorting if needed
                if sort_key_str in ["iv", "ev"]:
                    stats_json = row[f"{sort_key_str}_json"]
                    stats_dict = json.loads(stats_json) if stats_json else {}
                    p["_sort_value"] = sum(stats_dict.values()) if isinstance(stats_dict, dict) else sum(stats_dict) if isinstance(stats_dict, list) else 0
                
                results.append(p)
                
            if self.filter_can_evolve is not None and self.filter_can_evolve.isChecked():
                bag = self._bag_item_ids()
                results = [p for p in results if self._can_evolve(p, bag)]

            # Perform Python sorting for IV/EV
            if sort_key_str in ["iv", "ev"]:
                results.sort(key=lambda x: x.get("_sort_value", 0), reverse=reverse)
            
            return results
        except Exception as e:
            if self.logger:
                self.logger.log("error", f"Error fetching filtered Pokémon: {e}")
            return []

    # --- "Can evolve" filter ------------------------------------------
    @staticmethod
    def _bag_item_ids() -> set:
        from ..functions.pokedex_functions import return_id_for_item_name
        ids = set()
        try:
            for it in mw.ankimon_db.get_all_items() or []:
                if int(it.get("quantity") or 0) > 0:
                    i = return_id_for_item_name(it.get("item_name"))
                    if i is not None:
                        ids.add(str(i))
        except Exception:
            pass
        return ids

    def _item_gate(self, evo_id) -> int:
        """Evolution items: Lv 16 for a first evolution, Lv 30 for a second
        (setting: Evolution Items Need A Level) - same as the bag."""
        on = self.settings.get("evolution.item_level_gate", True)
        if isinstance(on, str):
            on = on.strip().lower() in ("1", "true", "yes", "on")
        if not on:
            return 0
        try:
            from .item_window import ItemWindow
            return 30 if ItemWindow._evo_stage(evo_id) >= 2 else 16
        except Exception:
            return 16

    def _can_evolve(self, p, bag) -> bool:
        """Ready to evolve now: by level or friendship (the sparkle badge), or
        with an evolution item in the bag that it can use at its level."""
        try:
            if p.get("everstone"):
                return False
            r = evolution_readiness({"id": p["id"], "friendship": p.get("friendship", 0),
                                     "everstone": False,
                                     "evolution_rejected": p.get("evolution_rejected", False),
                                     "level": p.get("level", 1)})
            if r.get("ready") and (r.get("method") == "level"
                                   or self.settings.get("evolution.friendship_time_enabled", True)):
                return True
            if not bag:
                return False
            from ..functions.pokedex_functions import pokemon_evolves_from_id, get_pokemon_evolution_data
            lv = int(p.get("level") or 1)
            for evo in pokemon_evolves_from_id(int(p["id"])) or []:
                d = get_pokemon_evolution_data(int(evo)) or {}
                trig = str(d.get("evolution_trigger_id") or "")
                item = (str(d.get("trigger_item_id") or "") if trig == "3"
                        else str(d.get("held_item_id") or "") if trig == "2" else "")
                if item and item in bag and lv >= self._item_gate(int(d.get("evolved_species_id") or evo)):
                    return True
        except Exception:
            pass
        return False

    def keyPressEvent(self, event):
        """Enter in the search box just searches. Without this the dialog
        also 'clicks' its default button - the first Pokémon slot."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def on_sort_button_clicked(self, button):
        self.selected_sort_key = button.text()
        self.go_to_box(0)

    def show_actions_submenu(self, button: QPushButton, pokemon: dict[str, Any]):
        """
        Displays a context menu with actions related to a specific Pokémon.

        The menu includes:
        - A non-interactive title showing the Pokémon's nickname, name, gender symbol, and level.
        - An option to view detailed information about the Pokémon.
        - An option to select the Pokémon as the main Pokémon.
        - An option to toggle the Pokémon's favorite status.

        Args:
            button (QPushButton): The button widget where the menu will be displayed.
            Pokémon (dict[str, Any]): A dictionary containing Pokémon data, expected to include keys
                like "name", "nickname", "gender", "level", and "is_favorite".

        Side Effects:
            - Displays a popup menu aligned below the specified button.
            - Connects menu actions to respective handlers in the parent class.
        """
        menu = QMenu(self)

        # Emulate a window title for QMenu
        if pokemon.get("gender") == "M":
            gender_symbol = "♂"
        elif pokemon.get("gender") == "F":
            gender_symbol = "♀"
        else:
            gender_symbol = ""
        if pokemon.get("nickname"):
            title = f"{pokemon['nickname']} ({pokemon['name']}) {gender_symbol} - lvl {pokemon['level']}"
        else:
            title = f"{pokemon['name']} {gender_symbol} - lvl {pokemon['level']}"
        title_action = QAction(title, menu)
        title_action.setEnabled(False)  # Disabled, so it can't be clicked
        menu.addAction(title_action)
        menu.addSeparator()

        pokemon_details_action = QAction("Pokémon details", self)
        main_pokemon_action = QAction("Pick as main Pokémon", self)
        make_favorite_action = QAction(
            "Unmake favorite" if pokemon.get("is_favorite", False) else "Make favorite"
        )
        give_held_item = QAction("Give a held item", self)

        # Connect actions to methods or lambda functions
        pokemon_details_action.triggered.connect(lambda: self.show_pokemon_details(pokemon))
        main_pokemon_action.triggered.connect(lambda: self.main_pokemon_function_callback(mw.ankimon_db.get_pokemon(pokemon['individual_id'])))
        make_favorite_action.triggered.connect(lambda: self.toggle_favorite(pokemon))
        give_held_item.triggered.connect(lambda: self.give_held_item(pokemon))

        menu.addAction(pokemon_details_action)
        menu.addAction(main_pokemon_action)
        menu.addAction(make_favorite_action)
        menu.addAction(give_held_item)
        if pokemon.get("held_item"):
            remove_held_item = QAction(
                f"Remove held item : {format_item_name(pokemon['held_item'])}", self
            )
            remove_held_item.triggered.connect(lambda: self.remove_held_item(pokemon))
            menu.addAction(remove_held_item)

        # Show the menu at the button's position, aligned below the button
        menu.exec(button.mapToGlobal(button.rect().topRight()))

    def show_pokemon_details(self, pokemon_stub):
        """
        Displays detailed information about a specific Pokémon in the right-hand details panel.

        The method prepares detailed stats by merging base stats or stats with experience points,
        then updates the `self.details_layout` with a `PokemonCollectionDetails` layout.

        Args:
            pokemon_stub (dict): A lightweight dictionary containing the Pokémon's `individual_id`.
        """
        pokemon = mw.ankimon_db.get_pokemon(pokemon_stub['individual_id'])
        if not pokemon:
            return

        if pokemon.get('base_stats'):
            detail_stats = {**pokemon['base_stats'], "xp": pokemon.get("xp", 0)}
        elif pokemon.get('stats'):
            detail_stats = {**pokemon['stats'], "xp": pokemon.get("xp", 0)}
        else:
            raise ValueError("Could not get the stats information of the Pokémon")

        self.pokemon_details_layout = PokemonCollectionDetails(
            name=pokemon["name"],
            level=pokemon["level"],
            id=pokemon["id"],
            shiny=pokemon.get("shiny", False),
            ability=pokemon["ability"],
            type=pokemon["type"],
            detail_stats=detail_stats,
            attacks=pokemon["attacks"],
            base_experience=pokemon["base_experience"],
            growth_rate=pokemon["growth_rate"],
            ev=pokemon["ev"],
            iv=pokemon["iv"],
            gender=pokemon["gender"],
            nickname=pokemon.get("nickname"),
            individual_id=pokemon.get("individual_id"),
            pokemon_defeated=pokemon.get("pokemon_defeated", 0),
            everstone=pokemon.get("everstone", False),
            evolution_rejected=pokemon.get("evolution_rejected", False),
            captured_date=pokemon.get("captured_date", "Missing"),
            language=int(self.settings.get("misc.language")),
            gif_in_collection=self.gif_in_collection,
            remove_levelcap=self.settings.get("misc.remove_level_cap"),
            logger=self.logger,
            refresh_callback=self.refresh_gui,
            initial_tab_index=self.current_stats_tab_index,
            tab_changed_callback=self.on_stats_tab_changed,
            nature=pokemon.get("nature", "serious"),
            base_stats=pokemon.get("base_stats"),
            friendship=pokemon.get("friendship", 0),
            friendship_time_enabled=self.settings.get(
                "evolution.friendship_time_enabled", True
            ),
        )
        # Selecting a Pokémon only opens the details panel — no data change, so
        # reuse the cached BFF. (The refresh_callback above keeps the default
        # recompute=True for mutating actions like release/trade/rename/evolve.)
        self.refresh_gui(recompute_bff=False)

    def on_stats_tab_changed(self, index: int):
        """Callback to remember which tab (Stats/IV/EV) is selected."""
        self.current_stats_tab_index = index

    def toggle_favorite(self, pokemon: dict[list, Any]):
        """
        Toggles the favorite status of a specific Pokémon in the saved Pokémon data.

        This method loads the current Pokémon list, finds the Pokémon by its unique individual ID,
        switches its "is_favorite" status, saves the updated list back to file, and refreshes the GUI.

        Args:
            Pokémon (dict[list, Any]): A dictionary representing the Pokémon, expected to contain
                a unique "individual_id" key and a "name" key.

        Side Effects:
            - Updates the "is_favorite" status of the Pokémon in persistent storage.
            - Refreshes the GUI to reflect the change.
            - Logs an info message if the Pokémon is not found in the list.
        """
        target_pokemon = mw.ankimon_db.get_pokemon(pokemon["individual_id"])
        if target_pokemon:
            target_pokemon["is_favorite"] = not target_pokemon.get("is_favorite", False)
            mw.ankimon_db.save_pokemon(target_pokemon)
            self.refresh_gui()
            return

        if self.logger is not None:
            self.logger.log("info", f"Could not make/unmake {pokemon['name']} favorite")

    def give_held_item(self, pokemon_stub: dict):
        """
        Opens a window to select and give a held item to the specified Pokémon.

        This function reads the available items from the database, filters out
        non-holdable items (items with a non-None "type"), and presents the user with a
        selection window. Once an item is selected, it is assigned to the Pokémon, a
        confirmation message is shown, and the GUI is refreshed to reflect the change.

        Args:
            pokemon_stub (dict): A lightweight dictionary containing the Pokémon's `individual_id`.

        Returns:
            None

        Side Effects:
            - Opens a modal `GiveItemWindow` for item selection.
            - Updates the Pokémon's held item via `PokemonObject.give_held_item`.
            - Logs and displays an info message using `ShowInfoLogger`.
            - Refreshes the GUI via `self.refresh_gui()`.
        """
        pokemon = mw.ankimon_db.get_pokemon(pokemon_stub['individual_id'])
        if not pokemon:
            return

        items_list = mw.ankimon_db.get_all_items()
        # Filter to holdable items (items without a type, stored in data field)
        items_names = []
        for item in items_list:
            item_data = item.get("data") or {}
            if item_data.get("type") is None:
                items_names.append(item.get("item_name") or item_data.get("item", ""))
        items_names = [n for n in items_names if n]  # Remove empty strings
        pokemon_obj = PokemonObject.from_dict(pokemon)

        def func(item_name: str):
            # Callback to handle item assignment and GUI refresh
            pokemon_obj.give_held_item(item_name)
            self.logger.log_and_showinfo(
                "info", f"{item_name} was given to {pokemon.get('name')}."
            )
            self.refresh_gui()

        give_item_window = GiveItemWindow(
            item_list=items_names,
            give_item_func=lambda item_name: func(item_name),
            logger=self.logger,
        )
        give_item_window.exec()

    def remove_held_item(self, pokemon_stub: dict):
        """
        Removes the held item from the specified Pokémon.

        Converts the Pokémon dictionary into a `PokemonObject`, removes the held item,
        logs the change, and refreshes the GUI. If the Pokémon does not have a held item,
        raises a `ValueError`.

        Args:
            pokemon_stub (dict): A lightweight dictionary containing the Pokémon's `individual_id`.

        Returns:
            None

        Raises:
            ValueError: If the Pokémon does not currently hold an item.

        Side Effects:
            - Updates the Pokémon's data to remove the held item.
            - Logs and displays an info message using `ShowInfoLogger`.
            - Refreshes the GUI via `self.refresh_gui()`.
        """
        pokemon = mw.ankimon_db.get_pokemon(pokemon_stub['individual_id'])
        if not pokemon:
            return
            
        pokemon_obj = PokemonObject.from_dict(pokemon)
        if pokemon.get("held_item") is None:
            raise ValueError("The Pokémon does not hold an item.")
        pokemon_obj.remove_held_item()
        self.logger.log_and_showinfo(
            "info",
            f"{format_item_name(pokemon['held_item'])} was removed from {pokemon.get('name')}.",
        )

        # Refreshing the PC after giving the item is important in order to update the pokemon information without the held item
        self.refresh_gui()

    def ensure_data_integrity(self):
        """
        Iterates through all Pokémon to ensure they have required non-stat fields,
        adding default values if fields are missing. This handles data
        from older addon versions. Stat-related fields are ignored.
        """
        pokemon_list = mw.ankimon_db.get_all_pokemon()
        if not pokemon_list:
            return

        # --- QUICK CHECK ---
        # First, quickly determine if any migration is needed at all.
        default_keys = {
            "nickname",
            "gender",
            "ability",
            "type",
            "attacks",
            "base_experience",
            "growth_rate",
            "everstone",
            "evolution_rejected",
            "shiny",
            "captured_date",
            "individual_id",
            "mega",
            "special_form",
            "xp",
            "friendship",
            "pokemon_defeated",
            "tier",
            "is_favorite",
            "held_item",
            "cp",
        }

        is_migration_needed = any(
            key not in pokemon
            for pokemon in pokemon_list
            if isinstance(pokemon, dict)
            for key in default_keys
        )

        if not is_migration_needed:
            return  # All Pokémon are up-to-date, exit early.

        # --- FULL MIGRATION (only if needed) ---
        needs_update = False
        default_values = {
            "nickname": "",
            "gender": "N",
            "ability": "Illuminate",
            "type": ["Normal"],
            "attacks": ["Struggle"],
            "base_experience": 0,
            "growth_rate": "medium",
            "everstone": False,
            "evolution_rejected": False,
            "shiny": False,
            "captured_date": None,
            "individual_id": lambda p: str(uuid.uuid4()),
            "mega": False,
            "special_form": None,
            "xp": 0,
            "friendship": 0,
            "pokemon_defeated": 0,
            "tier": lambda p: get_tier_by_id(p.get("id", 0)) or "Normal",
            "is_favorite": False,
            "held_item": None,
            "cp": lambda p: calculate_cp_from_dict(p),
        }

        for i, pokemon in enumerate(pokemon_list):
            if not isinstance(pokemon, dict):
                continue

            for key, default_generator in default_values.items():
                if key not in pokemon:
                    needs_update = True
                    if callable(default_generator):
                        value = default_generator(pokemon)
                    else:
                        value = default_generator
                    pokemon_list[i][key] = value

        if needs_update:
            for pokemon in pokemon_list:
                mw.ankimon_db.save_pokemon(pokemon)

    def on_window_close(self):
        if self.pokemon_details_layout is not None:
            clear_layout(self.pokemon_details_layout)
            self.details_widget.setFixedSize(0, 0)
            self.pokemon_details_layout = None

    def closeEvent(self, event: QCloseEvent):
        self.on_window_close()
        event.accept()  # Accept the close event

    def reject(self):  # Called when pressing Escape
        self.on_window_close()
        super().reject()


class GiveItemWindow(QDialog):
    """
    Small window that opens up when the user gives an item to the Pokémon from a PC box
    """

    # Make it a class variable so it can be accessed from other classes
    NOT_YET_IMPLEMENTED_ITEMS = {
        "focus-sash",
        "focus-band",
        "white-herb",
        "mental-herb",
        "power-herb",
        "throat-spray",
        "weakness-policy",
    }

    def __init__(self, item_list: list[str], give_item_func: Callable, logger):
        super().__init__()
        self.setWindowTitle("Give an Item")
        self.resize(400, 400)

        # Outer layout for the dialog
        main_layout = QVBoxLayout(self)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        # Container widget inside scroll area
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        self.give_item_func = give_item_func
        self.logger = logger

        # Add item rows
        for item in item_list:
            row_layout = QHBoxLayout()

            item_label = QLabel(format_item_name(item))
            give_button = QPushButton(f"Give {format_item_name(item)}")
            give_button.clicked.connect(
                lambda clicked, i=item: self.expanded_give_item_func(i)
            )
            if (
                item in GiveItemWindow.NOT_YET_IMPLEMENTED_ITEMS
                or item.endswith("-berry")
                or item.endswith("-gem")
            ):
                # NOTE (Axil): As time of writing, single use items are not yet implemented.
                # It seems to me that, actually, they are not even implemented in the Poke-engine. Although
                # I haven't dug too much.
                # Therefore, for now, and hopefully as a not too permanent temporary fix, I will prevent the
                # user from giving out single-use items.
                give_button.setToolTip("Single use held items are not yet implemented.")
                give_button.setEnabled(False)
                give_button.clicked.connect(
                    lambda clicked: self.logger.log_and_showinfo(
                        "info", "Single use held items are not yet implemented."
                    )
                )

            row_layout.addWidget(item_label)
            row_layout.addStretch()
            row_layout.addWidget(give_button)

            # Optional: separate rows with a line
            row_frame = QFrame()
            row_frame.setLayout(row_layout)
            scroll_layout.addWidget(row_frame)

        scroll_content.setLayout(scroll_layout)
        scroll.setWidget(scroll_content)

        # Add scroll area to main layout
        main_layout.addWidget(scroll)
        self.setLayout(main_layout)

    def expanded_give_item_func(self, item_name: str):
        # Wrapper to close window after giving item
        self.give_item_func(item_name)
        self.close()
