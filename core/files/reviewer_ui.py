import json

from anki.hooks import wrap
from aqt.reviewer import Reviewer
from aqt.utils import downArrow, tooltip, tr

from .singletons import (
    enemy_pokemon,
    main_pokemon,
    ankimon_tracker_obj,
    test_window,
    evo_window,
    logger,
    achievements,
    trainer_card,
    reviewer_obj,
    settings_obj,
)
from .functions.encounter_functions import (
    catch_pokemon,
    kill_pokemon,
    new_pokemon,
)
from .texts import _bottomHTML_template, button_style

_collected_pokemon_ids = set()


def set_collected_ids(ids):
    global _collected_pokemon_ids
    _collected_pokemon_ids = ids


def catch_shortcut_function():
    if enemy_pokemon.hp < 1:
        catch_pokemon(
            enemy_pokemon,
            ankimon_tracker_obj,
            logger,
            "",
            _collected_pokemon_ids,
            achievements,
        )
        new_pokemon(enemy_pokemon, test_window, ankimon_tracker_obj, reviewer_obj)
    else:
        tooltip("You only catch a Pokémon once it's fainted!")


def defeat_shortcut_function():
    if enemy_pokemon.hp < 1:
        kill_pokemon(
            main_pokemon, enemy_pokemon, evo_window, logger, achievements, trainer_card
        )
        new_pokemon(enemy_pokemon, test_window, ankimon_tracker_obj, reviewer_obj)
    else:
        tooltip("Wild Pokémon has to be fainted to defeat it!")


def buttons_shown() -> bool:
    """Catch/Defeat buttons only matter when you choose yourself: Show Pokémon Buttons
    on and Automatic Battle 0 (1-3 catch or defeat on their own)."""
    on = settings_obj.get("controls.pokemon_buttons", True)
    if isinstance(on, str):
        on = on.strip().lower() in ("true", "1", "yes")
    try:
        auto = int(settings_obj.get("battle.automatic_battle", 0))
    except (TypeError, ValueError):
        auto = 0
    return bool(on) and auto not in (1, 2, 3)


def refresh_buttons():
    """Show or hide the buttons as soon as Settings are saved, mid-review too."""
    from aqt import mw
    web = getattr(getattr(getattr(mw, "reviewer", None), "bottom", None), "web", None)
    if web is None or getattr(mw, "state", None) != "review":
        return
    web.eval("(function(){var b=document.getElementById('ankimon_buttons');"
             "if(b){b.style.display=%s;}})();" % json.dumps("" if buttons_shown() else "none"))


def setup_reviewer_ui(catch_shortcut: str, defeat_shortcut: str, reviewer_buttons: bool = True):
    # reviewer_buttons (the setting when Anki started) is unused: buttons_shown() reads it live
    catch_key = str(catch_shortcut).lower()
    defeat_key = str(defeat_shortcut).lower()

    def _shortcutKeys_wrap(self, _old):
        original = _old(self)
        original.append((catch_key, lambda: catch_shortcut_function()))
        original.append((defeat_key, lambda: defeat_shortcut_function()))
        return original

    Reviewer._shortcutKeys = wrap(Reviewer._shortcutKeys, _shortcutKeys_wrap, "around")

    Review_linkHandler_Original = Reviewer._linkHandler

    def linkHandler_wrap(reviewer, url):
        if url == "catch":
            catch_shortcut_function()
        elif url == "defeat":
            defeat_shortcut_function()
        else:
            Review_linkHandler_Original(reviewer, url)

    def _bottomHTML(self) -> str:
        return _bottomHTML_template % dict(
            edit=tr.studying_edit(),
            editkey=tr.actions_shortcut_key(val="E"),
            more=tr.studying_more(),
            morekey=tr.actions_shortcut_key(val="M"),
            downArrow=downArrow(),
            time=self.card.time_taken() // 1000,
            CatchKey=tr.actions_shortcut_key(val=f"{catch_key}"),
            DefeatKey=tr.actions_shortcut_key(val=f"{defeat_key}"),
            ButtonsStyle="" if buttons_shown() else "display:none",
        )

    Reviewer._bottomHTML = _bottomHTML
    Reviewer._linkHandler = linkHandler_wrap
    try:
        from .pyobj.settings import SAVE_HOOKS
        SAVE_HOOKS.append(refresh_buttons)
    except ImportError:
        pass
