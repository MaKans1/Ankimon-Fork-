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
)
from .functions.encounter_functions import (
    catch_pokemon,
    kill_pokemon,
    new_pokemon,
)

catch_pokemon_hooks = []
defeat_pokemon_hooks = []


def add_catch_pokemon_hook(func):
    catch_pokemon_hooks.append(func)


def add_defeat_pokemon_hook(func):
    defeat_pokemon_hooks.append(func)


def CatchPokemonHook(collected_pokemon_ids):
    if enemy_pokemon.hp < 1:
        catch_pokemon(
            enemy_pokemon,
            ankimon_tracker_obj,
            logger,
            "",
            collected_pokemon_ids,
            achievements,
        )
        new_pokemon(
            enemy_pokemon, test_window, ankimon_tracker_obj, reviewer_obj
        )
    for hook in catch_pokemon_hooks:
        hook()


def DefeatPokemonHook():
    if enemy_pokemon.hp < 1:
        kill_pokemon(
            main_pokemon, enemy_pokemon, evo_window, logger, achievements, trainer_card
        )
        new_pokemon(
            enemy_pokemon, test_window, ankimon_tracker_obj, reviewer_obj
        )
    for hook in defeat_pokemon_hooks:
        hook()
