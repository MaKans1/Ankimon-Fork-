import json
import random
import math
from typing import Union
from datetime import datetime
import uuid

from aqt import mw
from aqt.qt import QDialog
from aqt.utils import showWarning

from ..pyobj.ankimon_tracker import AnkimonTracker
from ..pyobj.pokemon_obj import PokemonObject
from ..pyobj.reviewer_obj import Reviewer_Manager
from ..pyobj.test_window import TestWindow
from ..pyobj.trainer_card import TrainerCard
from ..pyobj.InfoLogger import ShowInfoLogger
from ..pyobj.evolution_window import EvoWindow
from ..pyobj.attack_dialog import AttackDialog
from ..pyobj.translator import Translator
from ..functions.pokemon_functions import (
    find_experience_for_level,
    get_levelup_move_for_pokemon,
    pick_random_gender,
    shiny_chance,
)
from ..functions.pokedex_functions import (
    display_name,
    pokemon_key,
    check_evolution_for_pokemon,
    get_all_pokemon_moves,
    get_base_experience,
    get_effort_values,
    get_growth_rate,
    return_name_for_id,
    search_pokedex,
    search_pokedex_by_id,
)
from ..functions.friendship_evolution import (
    check_friendship_evolution_for_pokemon,
)
from ..pyobj.error_handler import show_warning_with_traceback
from ..functions.trainer_functions import xp_share_gain_exp
from ..functions.badges_functions import check_for_badge, receive_badge
from ..functions.drawing_utils import tooltipWithColour
from ..utils import limit_ev_yield, play_effect_sound, get_ev_spread
from ..business import calc_experience, calculate_cp_from_dict
from ..const import gen_ids
from ..singletons import (
    main_pokemon,
    ankimon_tracker_obj,
    trainer_card,
    settings_obj,
    translator,
    ankimon_db,
    pokemon_pc,
)


_percentages_cache = {
    'percentages': None,
    'total_reviews': None,
    'trainer_level': None,
    'main_pokemon_level': None,
}

def _wild_popup(kind):
    """Wild-battle popup toggles (Settings > Battle > Wild Battle Popups)."""
    try:
        from ..wild import wild_rules as _wild
        return _wild.popup(kind)
    except Exception:
        return True


def _wild_share_exp(exp, finisher, logger, evo_window):
    """Final blow 50%, the rest split between the other Pokémon that fought."""
    try:
        from ..wild import wild_rules as _wild
        return _wild.share_exp(exp, finisher, logger, evo_window)
    except Exception as e:
        print("Ankimon: EXP split skipped:", e)
        return exp


def modify_percentages(total_reviews, daily_average, trainer_level):
    """
    Modify Pokémon encounter percentages based on total reviews, trainer level, and main Pokémon level.
    """
    # Performance Guard: Skip recalculation if inputs haven't changed
    if (_percentages_cache['percentages'] is not None and
        _percentages_cache['total_reviews'] == total_reviews and
        _percentages_cache['trainer_level'] == trainer_level and
        _percentages_cache['main_pokemon_level'] == main_pokemon.level):
        return _percentages_cache['percentages']

    # Start with the base percentages
    percentages = {"Baby": 2, "Legendary": 0.5, "Mythical": 0.2, "Normal": 92.3, "Ultra": 5}

    # Adjust percentages based on total reviews relative to the daily average
    review_ratio = total_reviews / daily_average if daily_average > 0 else 0

    # Adjust for review progress
    if review_ratio < 0.4:
        percentages["Normal"] += percentages.pop("Baby", 0) + percentages.pop("Legendary", 0) + \
                                 percentages.pop("Mythical", 0) + percentages.pop("Ultra", 0)
    elif review_ratio < 0.6:
        percentages["Baby"] += 2
        percentages["Normal"] -= 2
    elif review_ratio < 0.8:
        percentages["Ultra"] += 3
        percentages["Normal"] -= 3
    else:
        percentages["Legendary"] += 2
        percentages["Ultra"] += 3
        percentages["Normal"] -= 5

    # Restrict access to certain tiers based on main Pokémon level
    if main_pokemon.level:
        # Define level thresholds for each tier
        level_thresholds = {
            "Ultra": 30,  # Example threshold for Ultra Pokémon
            "Legendary": 50,  # Example threshold for Legendary Pokémon
            "Mythical": 75  # Example threshold for Mythical Pokémon
        }

        for tier in ["Ultra", "Legendary", "Mythical"]:
            if main_pokemon.level < level_thresholds.get(tier, float("inf")):
                percentages[tier] = 0  # Set percentage to 0 if the level requirement isn't met

    # Example modification based on trainer level
    if trainer_level:
        adjustment = 5  # Adjustment value for the example
        if trainer_level > 10:
            for tier in percentages:
                if tier == "Normal":
                    percentages[tier] = max(percentages[tier] - adjustment, 0)
                else:
                    percentages[tier] = percentages.get(tier, 0) + adjustment

    # Normalize percentages to ensure they sum to 100
    total = sum(percentages.values())
    for tier in percentages:
        percentages[tier] = (percentages[tier] / total) * 100 if total > 0 else 0

    # Cache and return
    _percentages_cache['percentages'] = percentages
    _percentages_cache['total_reviews'] = total_reviews
    _percentages_cache['trainer_level'] = trainer_level
    _percentages_cache['main_pokemon_level'] = main_pokemon.level
    
    # this function gets called maybe 10 times per battle round, which is concerning.
    # it could be rewritten to run ONLY when the change in review ratio is detected.
    return percentages


def get_random_pokemon_in_tier(tier):
    from . import encounter_data

    if tier == "Normal":
        id_data = encounter_data.NORMAL
    elif tier == "Baby":
        id_data = encounter_data.BABY
    elif tier == "Ultra":
        id_data = encounter_data.ULTRA
    elif tier == "Legendary":
        id_data = encounter_data.LEGENDARY
    elif tier == "Mythical":
        id_data = encounter_data.MYTHICAL
    else:
        raise ValueError()

    # Select a random Pokemon ID from those in the tier, pre-filtered by the
    # chosen region (or the Generation settings) so the spawn loop rarely retries
    try:
        from ..wild import wild_rules as _wild
        id_data = _wild.filter_ids(id_data) or id_data
    except Exception:
        pass
    random_pokemon_id = random.choice(id_data)
    return random_pokemon_id


def get_tier(total_reviews, trainer_level=1, event_modifier=None):
    """_summary_
    Randomly picks the tier for a new enemy Pokémon to be generated from, based on weighted probabilities based on number of reviews and trainer level.

    Args:
        total_reviews (int): Number of reviews done in that Anki session.
        trainer_level (int, optional): Trainer XP level. Defaults to 1.
        event_modifier (?, optional): Unused argument. Defaults to None.

    Returns:
        choice[0]: The first choice of TIER picked randomly (by a random.choices function)
    """
    daily_average = int(settings_obj.get("battle.daily_average"))
    percentages = modify_percentages(total_reviews, daily_average, trainer_level)

    tiers = list(percentages.keys())
    probabilities = list(percentages.values())

    choice = random.choices(tiers, probabilities, k=1)
    return choice[0]


def choose_random_pkmn_from_tier():
    """
    Runs a tier-selection and a subsequent ID-selection function to pick a random Pokemon from a given randomly picked Tier.
    The tier is a weighted probability selection, based on total_reviews and trainer_level.
    Pokemon ID is picked randomly from within that tier.

    Returns:
        id (int): Pokedex ID for generated Pokemon
        tier (str): Rarity tier for generated Pokemon (normal/ultra/legendary etc.)
    """
    total_reviews = ankimon_tracker_obj.get_total_reviews()
    trainer_level = trainer_card.level
    try:
        tier = get_tier(total_reviews, trainer_level)
        id = get_random_pokemon_in_tier(tier)
        mw.logger.game_log(f"Selected tier: {tier}, Resulting Pokémon ID: {id}")
        return id, tier
    except Exception as e:
        mw.logger.log("error", f"Error in choose_random_pkmn_from_tier: {str(e)}")
        show_warning_with_traceback(parent=mw, exception=e, message="Error occurred")


def check_min_generate_level(name):
    evoType = search_pokedex(name.lower(), "evoType")
    evoLevel = search_pokedex(name.lower(), "evoLevel")
    if evoLevel:
        return int(evoLevel)
    # Pikachu, Clefairy, Snorlax...: only their baby form is "earlier", and
    # they are ordinary wild Pokemon in the real games.
    try:
        from ..wild import wild_rules as _wild
        _baby_min = _wild.baby_prevo_min_level(name)
        if _baby_min is not None:
            return _baby_min
    except Exception:
        pass
    if evoType != []:
        min_level = 100
        return min_level
    else:
        min_level = 1
        return min_level


def check_id_ok(id_num: Union[int, list[int]]):
    if isinstance(id_num, list):
        if len(id_num) > 0:
            id_num = id_num[0]
        else:
            return False

    if not isinstance(id_num, int):
        return False

    # Game -> Choose Region overrides the Generation checkboxes
    try:
        from ..wild import wild_rules as _wild
        _in_region = _wild.region_allows(id_num)
        if _in_region is not None:
            return _in_region
    except Exception:
        pass

    generation = 0
    for gen, max_id in gen_ids.items():
        if id_num <= max_id:
            generation = int(gen.split("_")[1])

            gen_config = [settings_obj.get(f"misc.gen{i}") for i in range(1, 10)]
            return gen_config[generation - 1]

    return False


def generate_random_pokemon(
    main_pokemon_level: int, ankimon_tracker_obj: AnkimonTracker
):
    """
    Generates a random wild Pokémon with attributes scaled to the level of the player's main Pokémon.

    This function resets the encounter and battle round state in the provided `AnkimonTracker` object.
    It then selects a valid Pokémon that can appear at the current level range, computes its stats,
    determines its moves, ability, and other combat-relevant characteristics, and returns all necessary
    data required for a battle.

    Args:
        main_pokemon_level (int): The level of the player's main Pokémon. Determines the level range of
            the generated wild Pokémon.
        ankimon_tracker_obj (AnkimonTracker): An object used to track battle state, such as the number
            of Pokémon encountered and cards used in the battle.

    Returns:
        tuple: A tuple containing the following elements:
            - name (str): Name of the wild Pokémon.
            - pokemon_id (int): Unique ID of the Pokémon.
            - wild_pokemon_lvl (int): The level of the generated Pokémon.
            - ability (str): The selected ability of the Pokémon.
            - pokemon_type (list[str]): List of type(s) the Pokémon belongs to.
            - base_stats (dict): Dictionary of the Pokémon's base stats.
            - moves (list[str]): List of up to 4 moves the Pokémon can use in battle.
            - base_experience (int): Experience points awarded for defeating the Pokémon.
            - growth_rate (str): Growth rate category of the Pokémon (e.g., "slow", "fast").
            - ev (dict): Effort values (EVs) for each stat, initialized to 0.
            - iv (dict): Randomly generated individual values (IVs) for each stat.
            - gender (str): Randomly assigned gender.
            - battle_status (str): Current status of the Pokémon in battle, defaulted to "fighting".
            - final_stats (dict): Final computed stats of the Pokémon.
            - tier (str): Tier from which the Pokémon was selected (e.g., common, rare).
            - ev_yield (dict): Effort values (EVs) awarded upon defeating the Pokémon.
            - is_shiny (bool): Indicates whether the Pokémon is shiny.

    Raises:
        ValueError: If no valid Pokémon can be generated (highly unlikely under normal conditions).
    """
    lvl_variation = 3
    lvl_range = (
        max(1, main_pokemon_level - lvl_variation),
        max(1, main_pokemon_level + lvl_variation),
    )
    wild_pokemon_lvl = random.randint(*lvl_range)
    wild_pokemon_lvl = max(
        1, wild_pokemon_lvl
    )  # Ensures that the wild pokemon's level is at least 1
    if main_pokemon_level == 100:
        wild_pokemon_lvl = 100
    # Wild Levels Follow Badges: Red/Blue-style route levels (+ rare strong ones)
    try:
        from ..wild import wild_rules as _wild
        _band_lvl = _wild.pick_level(main_pokemon_level)
        if _band_lvl:
            wild_pokemon_lvl = int(_band_lvl)
    except Exception:
        pass

    # First, we draw a random, valid pokemon id.
    pokemon_id, tier = choose_random_pkmn_from_tier()
    name = search_pokedex_by_id(pokemon_id)
    min_allowed_pokemon_lvl = check_min_generate_level(
        str(name.lower())
    )  # Gets the minimum allowed level for that pokemon given its stage of evolution

    attempts = 0
    while (not check_id_ok(pokemon_id)) or (
        wild_pokemon_lvl < min_allowed_pokemon_lvl
    ):  # We keep drawing a random pokemon until we find a valid one
        attempts += 1
        if attempts >= 500:
            showWarning("Failed to generate a valid Pokémon after 500 attempts. Please ensure at least one generation is enabled in the settings. Defaulting to Rattata.")
            pokemon_id = 19
            name = search_pokedex_by_id(19)
            tier = "Normal"
            min_allowed_pokemon_lvl = check_min_generate_level(str(name.lower()))
            wild_pokemon_lvl = max(wild_pokemon_lvl, min_allowed_pokemon_lvl)
            break

        pokemon_id, tier = choose_random_pkmn_from_tier()
        name = search_pokedex_by_id(pokemon_id)
        min_allowed_pokemon_lvl = check_min_generate_level(
            str(name.lower())
        )  # Gets the minimum allowed level for that pokemon given its stage of evolution

    # Rare spawns: wild starters (~1 in 100) and, once unlocked, Mewtwo
    _special = None
    try:
        from ..wild import wild_rules as _wild
        _special = _wild.special_spawn()
        if _special:
            pokemon_id, tier = _special["id"], _special["tier"]
            name = search_pokedex_by_id(pokemon_id)
            if _special.get("level"):
                wild_pokemon_lvl = int(_special["level"])
    except Exception:
        _special = None

    # Now we get all necessary information about the chosen pokemon.
    pokemon_type = search_pokedex(name, "types")
    base_experience = get_base_experience(
        search_pokedex(name, "actual_id")
    )  # Experience that the wild pokemon will give once beaten
    growth_rate = get_growth_rate(pokemon_id)
    ev_yield = get_effort_values(search_pokedex(name, "actual_id"))
    gender = pick_random_gender(name)
    is_shiny = shiny_chance()
    try:
        from ..wild import wild_rules as _wild
        if _wild.consume_shiny_block():
            is_shiny = False
    except Exception:
        pass
    battle_status = "fighting"
    base_stats = search_pokedex(name, "baseStats")

    all_possible_moves = get_all_pokemon_moves(name, wild_pokemon_lvl)
    if len(all_possible_moves) <= 4:
        moves = all_possible_moves
    else:
        moves = random.sample(all_possible_moves, 4)
    if _special and _special.get("moves"):
        moves = list(_special["moves"])

    ability = "no_ability"  # Default value for ability
    possible_abilities = search_pokedex(name, "abilities")
    if possible_abilities:
        numeric_abilities = {k: v for k, v in possible_abilities.items() if k.isdigit()}
        if numeric_abilities:
            ability = random.choice(list(numeric_abilities.values()))

    stat_names = ["hp", "atk", "def", "spa", "spd", "spe"]
    # ev = {stat: 0 for stat in stat_names}
    ev = get_ev_spread(random.choice(["random", "pair", "defense", "uniform"]))
    # tau = 200
    # mu = 31 * (1 - math.exp(-ankimon_tracker_obj.total_reviews / tau))  # At total reviews > 3 * tau, we get mu ~= 31
    # iv = {stat: iv_rand_gauss(mu=mu, sigma=5) for stat in stat_names}  # The higher the number of reviews, the higher the IVs
    iv = {stat: random.randint(0, 31) for stat in stat_names}
    final_stats = base_stats

    ankimon_tracker_obj.pokemon_encounter = 0  # 0: Start of Battle: 1: Current Battle
    ankimon_tracker_obj.cards_battle_round = 0  # Amount of cards in this current battle

    return (
        name,
        pokemon_id,
        wild_pokemon_lvl,
        ability,
        pokemon_type,
        base_stats,
        moves,
        base_experience,
        growth_rate,
        ev,
        iv,
        gender,
        battle_status,
        final_stats,
        tier,
        ev_yield,
        is_shiny,
    )


def new_pokemon(
    pokemon: PokemonObject,
    test_window: TestWindow,
    ankimon_tracker: AnkimonTracker,
    reviewer_obj: Reviewer_Manager,
) -> PokemonObject:
    """
    Initializes a new wild Pokémon encounter by generating a random Pokémon,
    updating its stats, setting its HP, and preparing the battle scene.

    This function uses the player's main Pokémon level to generate an appropriately
    leveled wild Pokémon with randomized attributes. It updates the provided `Pokémon`
    object with generated data, resets HP, triggers any battle scene randomization,
    and updates the reviewer interface if applicable.

    Args:
        Pokémon (PokemonObject): The Pokémon object to be updated with the new wild Pokémon's data.
        test_window (TestWindow): Optional UI window to display the first encounter scene.
        ankimon_tracker (AnkimonTracker): Object tracking battle-related state and handling battle scene randomization.
        reviewer_obj (Reviewer_Manager): Manager object responsible for updating battle review elements like life bars.

    Returns:
        PokemonObject: The updated `Pokémon` object representing the newly generated wild Pokémon ready for battle.
    """
    (
        name,
        pkmn_id,
        level,
        ability,
        pkmn_type,
        base_stats,
        enemy_attacks,
        base_experience,
        growth_rate,
        ev,
        iv,
        gender,
        battle_status,
        battle_stats,
        tier,
        ev_yield,
        is_shiny,
    ) = generate_random_pokemon(main_pokemon.level, ankimon_tracker_obj)
    pokemon_data = {
        "name": display_name(name),
        "id": pkmn_id,
        "level": level,
        "ability": ability,
        "type": pkmn_type,
        "base_stats": base_stats,
        "attacks": enemy_attacks,
        "base_experience": base_experience,
        "growth_rate": growth_rate,
        "ev": ev,
        "iv": iv,
        "gender": gender,
        "battle_status": battle_status,
        "battle_stats": battle_stats,
        "stat_stages": {
            "atk": 0,
            "def": 0,
            "spa": 0,
            "spd": 0,
            "spe": 0,
            "accuracy": 0,
            "evasion": 0,
        },
        "tier": tier,
        "ev_yield": ev_yield,
        "shiny": is_shiny,
    }
    pokemon.update_stats(**pokemon_data)
    max_hp = pokemon.calculate_max_hp()
    pokemon.current_hp = max_hp
    pokemon.hp = max_hp
    pokemon.max_hp = max_hp
    try:
        from ..wild import wild_rules as _wild
        _wild.on_new_encounter(pokemon)
    except Exception:
        pass

    ankimon_tracker.randomize_battle_scene()
    if test_window is not None:
        test_window.display_first_encounter()

    class Container(object):
        pass

    reviewer = Container()
    reviewer.web = mw.reviewer.web
    reviewer_obj.update_life_bar(reviewer, 0, 0)

    return pokemon


def save_main_pokemon_progress(
    main_pokemon: PokemonObject,
    enemy_pokemon: PokemonObject,
    exp: int,
    achievements: dict,
    logger: ShowInfoLogger,
    evo_window: EvoWindow,
):
    experience = int(
        find_experience_for_level(
            main_pokemon.growth_rate,
            main_pokemon.level,
            settings_obj.get("misc.remove_level_cap"),
        )
    )
    if settings_obj.get("misc.remove_level_cap") is True:
        main_pokemon.xp += exp
        level_cap = None
    elif main_pokemon.level != 100:
        main_pokemon.xp += exp
        level_cap = 100
    else:
        # Cap is on AND the main is already level 100: no XP is granted, but
        # level_cap must still be defined or the while-loop condition below
        # raises NameError and crashes every post-cap defeat (upstream #402).
        level_cap = 100
    try:
        db = mw.ankimon_db
        main_pokemon_data = db.get_main_pokemon()
        if not main_pokemon_data:
            showWarning(translator.translate("missing_mainpokemon_data"))
    except Exception as e:
        mw.logger.log("error", f"Error loading main Pokémon data: {str(e)}")
        show_warning_with_traceback(
            parent=mw, exception=e, message="Error loading main Pokémon data."
        )
        return
    evolution_prompted = False
    while int(
        find_experience_for_level(
            main_pokemon.growth_rate,
            main_pokemon.level,
            settings_obj.get("misc.remove_level_cap"),
        )
    ) < int(main_pokemon.xp) and (level_cap is None or main_pokemon.level < level_cap):
        main_pokemon.level += 1
        msg = ""
        msg += f"Your {main_pokemon.name} is now level {main_pokemon.level} !"
        color = "#6A4DAC"  # pokemon leveling info color for tooltip
        check = check_for_badge(achievements, 5)
        if check is False:
            achievements = receive_badge(5, achievements)
        try:
            mw.logger.game_log(f"Level Up: {msg}")
            if _wild_popup("levelup"):
                tooltipWithColour(msg, color)
        except:
            pass
        if False is True:
            logger.log_and_showinfo("info", f"{msg}")
        main_pokemon.xp = int(max(0, int(main_pokemon.xp) - int(experience)))

        # Request to open the pokemon evo window
        evo_id = check_evolution_for_pokemon(
            main_pokemon.individual_id,
            main_pokemon.id,
            main_pokemon.level,
            evo_window,
            main_pokemon.everstone,
            getattr(main_pokemon, "evolution_rejected", False),
        )
        if evo_id is not None:
            evolution_prompted = True
            # None-safe: return_name_for_id can return None for an unknown id, so
            # fall back to the numeric id instead of crashing on .capitalize()
            # (mirrors the friendship-evolution path below).
            evo_display_name = return_name_for_id(evo_id)
            evo_display_name = (
                display_name(evo_display_name) if evo_display_name else str(evo_id)
            )
            logger.log_and_showinfo(
                "info",
                translator.translate(
                    "pokemon_about_to_evolve",
                    main_pokemon_name=main_pokemon.name,
                    evo_pokemon_name=evo_display_name,
                    main_pokemon_level=main_pokemon.level,
                ),
            )

        if main_pokemon_data:
            mainpkmndata = main_pokemon_data
            if pokemon_key(mainpkmndata["name"]) == pokemon_key(main_pokemon.name):
                attacks = mainpkmndata["attacks"]
                new_attacks = get_levelup_move_for_pokemon(
                    main_pokemon.name.lower(), int(main_pokemon.level)
                )
                if new_attacks:
                    msg = ""
                    msg += translator.translate(
                        "mainpokemon_can_learn_new_attack",
                        main_pokemon_name=display_name(main_pokemon.name),
                    )
                for new_attack in new_attacks:
                    if len(attacks) < 4 and new_attack not in attacks:
                        attacks.append(new_attack)
                        msg += translator.translate(
                            "mainpokemon_learned_new_attack",
                            new_attack_name=new_attack,
                            main_pokemon_name=display_name(main_pokemon.name),
                        )
                        color = "#6A4DAC"
                        if _wild_popup("levelup"):
                            tooltipWithColour(msg, color)
                        if (
                            False
                            is True
                        ):
                            logger.log_and_showinfo("info", f"{msg}")
                    else:
                        dialog = AttackDialog(attacks, new_attack)
                        if dialog.exec() == QDialog.DialogCode.Accepted:
                            selected_attack = dialog.selected_attack
                            index_to_replace = None
                            for index, attack in enumerate(attacks):
                                if attack == selected_attack:
                                    index_to_replace = index
                            # If the attack is found, replace it with 'new_attack'
                            if index_to_replace is not None:
                                attacks[index_to_replace] = new_attack
                                logger.log_and_showinfo(
                                    "info",
                                    f"Replaced '{selected_attack}' with '{new_attack}'",
                                )
                            else:
                                logger.log_and_showinfo(
                                    "info", f"'{selected_attack}' not found in the list"
                                )
                        else:
                            # Handle the case where the user cancels the dialog
                            logger.log_and_showinfo(
                                "info", f"{new_attack} will be discarded."
                            )
                mainpkmndata["attacks"] = attacks
                # the live buddy is what wild battles use: give it the new move now
                main_pokemon.attacks = list(attacks)
    msg = ""
    msg += translator.translate(
        "mainpokemon_gained_xp",
        main_pokemon_name=main_pokemon.name,
        exp=exp,
        experience_till_next_level=experience,
        main_pokemon_xp=main_pokemon.xp,
    )
    color = "#a17cf7"  # pokemon leveling info color for tooltip
    if _wild_popup("xp"):
        tooltipWithColour(msg, color)
    if False is True:
        logger.log_and_showinfo("info", f"{msg}")

    # Load existing Pokémon data if it exists
    if main_pokemon_data:
        mainpkmndata = main_pokemon_data
        mainpkmndata["stats"] = main_pokemon.stats
        mainpkmndata["xp"] = int(main_pokemon.xp)
        mainpkmndata["level"] = int(main_pokemon.level)
        ev_yield = limit_ev_yield(mainpkmndata["ev"], enemy_pokemon.ev_yield)
        mainpkmndata["ev"]["hp"] += ev_yield["hp"]
        mainpkmndata["ev"]["atk"] += ev_yield["attack"]
        mainpkmndata["ev"]["def"] += ev_yield["defense"]
        mainpkmndata["ev"]["spa"] += ev_yield["special-attack"]
        mainpkmndata["ev"]["spd"] += ev_yield["special-defense"]
        mainpkmndata["ev"]["spe"] += ev_yield["speed"]
        # Mirror EV gain onto the in-memory object so CP/stats reads
        # stay consistent with the persisted dict until next restart.
        # Dict-item mutation doesn't fire __setattr__, so invalidate
        # the CP cache explicitly.
        main_pokemon.ev["hp"] += ev_yield["hp"]
        main_pokemon.ev["atk"] += ev_yield["attack"]
        main_pokemon.ev["def"] += ev_yield["defense"]
        main_pokemon.ev["spa"] += ev_yield["special-attack"]
        main_pokemon.ev["spd"] += ev_yield["special-defense"]
        main_pokemon.ev["spe"] += ev_yield["speed"]
        main_pokemon.invalidate_cp_cache()
        mainpkmndata["current_hp"] = int(main_pokemon.hp)
        # Friendship is uncapped — it keeps climbing past MAX_FRIENDSHIP (400) so
        # players can flex a super-bonded Pokémon. The progress bar still fills at
        # MAX_FRIENDSHIP; the raw number above it is what keeps growing.
        main_pokemon.friendship += random.randint(5, 9)
        mainpkmndata["friendship"] = main_pokemon.friendship
        if not evolution_prompted:
            friendship_evo_id = check_friendship_evolution_for_pokemon(
                main_pokemon.individual_id,
                main_pokemon.id,
                evo_window,
                main_pokemon.everstone,
                main_pokemon.friendship,
                getattr(main_pokemon, "evolution_rejected", False),
            )
            if friendship_evo_id is not None:
                evolution_prompted = True
                # return_name_for_id can return None (and pop a spurious warning)
                # if the evolved id is missing from the name CSV; guard the
                # .capitalize() so a data gap can't crash the defeat flow.
                friendship_evo_name = return_name_for_id(friendship_evo_id)
                friendship_evo_name = display_name(friendship_evo_name) if friendship_evo_name else str(friendship_evo_id)
                logger.log_and_showinfo(
                    "info",
                    translator.translate(
                        "pokemon_about_to_evolve_friendship",
                        main_pokemon_name=main_pokemon.name,
                        evo_pokemon_name=friendship_evo_name,
                    ),
                )
        main_pokemon.pokemon_defeated += 1
        mainpkmndata["pokemon_defeated"] = main_pokemon.pokemon_defeated
        if hasattr(main_pokemon, "tier"):
            mainpkmndata["tier"] = main_pokemon.tier
        if hasattr(main_pokemon, "is_favorite"):
            mainpkmndata["is_favorite"] = main_pokemon.is_favorite

        # Save to database (replaces JSON file I/O for performance)
        ankimon_db.save_main_pokemon(mainpkmndata)
        ankimon_db.save_pokemon(mainpkmndata)  # Also update the captured pokemon collection

    return main_pokemon.level

# --- Utility: Sync mainpokemon to mypokemon ---
def sync_mainpokemon_to_mypokemon(main_pokemon):
    """
    Update the relevant entry in mypokemon database with the latest values from mainpokemon.
    Uses database instead of JSON files.
    """
    db = mw.ankimon_db
    
    # Get main pokemon from database
    main_entry = db.get_main_pokemon()
    if not main_entry:
        return
    
    main_id = main_entry.get("individual_id", None)
    if not main_id:
        main_id = getattr(main_pokemon, "individual_id", None)
    if not main_id:
        return
    
    # Save/update in captured_pokemon table
    db.save_pokemon(main_entry)
    return

def kill_pokemon(
    main_pokemon: PokemonObject,
    enemy_pokemon: PokemonObject,
    evo_window: EvoWindow,
    logger: ShowInfoLogger,
    achievements: dict,
    trainer_card: Union[TrainerCard, None] = None,
):
    if trainer_card is not None:
        trainer_card.gain_xp(
            enemy_pokemon.tier, False
        )

    # Calculate experience based on whether moves are chosen manually
    exp = calc_experience(enemy_pokemon.base_experience, enemy_pokemon.level)
    if settings_obj.get("controls.allow_to_choose_moves"):
        exp *= 0.5
    exp *= _xp_multiplier("battle.defeat_xp_multiplier", 1.0)

    # Ensure exp is at least 1 and round up if it's a decimal
    exp = max(1, math.ceil(exp))

    # Wild team rotation: final blow keeps 50%, the rest is shared out
    exp = _wild_share_exp(exp, main_pokemon, logger, evo_window)

    # Handle XP share logic
    xp_share_individual_id = settings_obj.get("trainer.xp_share")
    if xp_share_individual_id:
        exp = xp_share_gain_exp(logger, settings_obj, evo_window, main_pokemon.id, exp, xp_share_individual_id)
    
    msg = ""

    if main_pokemon.held_item == "lucky-egg":
        exp = int(exp * 1.5)
        msg += f"{main_pokemon.name}'s Lucky Egg boosts its XP gained!\n"

    logger.log("info", msg)

    # Save main Pokémon's progress
    main_pokemon.level = save_main_pokemon_progress(
        main_pokemon,
        enemy_pokemon,
        exp,
        achievements,
        logger,
        evo_window,
    )

    ankimon_tracker_obj.general_card_count_for_battle = 0


def _average_iv(rec):
    """Mean IV across the six stats. Missing values count as 0."""
    iv = (rec or {}).get("iv") or {}
    keys = ("hp", "atk", "def", "spa", "spd", "spe")
    vals = []
    for k in keys:
        try:
            vals.append(int(iv.get(k, 0) or 0))
        except (TypeError, ValueError):
            vals.append(0)
    return sum(vals) / float(len(keys))


_DUP_NOTE = [""]    # result of the last duplicate check, shown with the catch


def _duplicate_verdict(caught, window=None):
    """(keep, best_owned, why) for a wild Pokémon against the copy you own.

    Regular and shiny copies are separate one-per-species slots: a wild shiny
    is compared only with your shiny copy, a regular one only with your
    regular copy. best_owned is None when that slot is empty (always keep).
    Outside the level window the higher level wins; inside it the higher
    average IV wins, whichever of the two is higher level."""
    if window is None:
        try:
            window = int(settings_obj.get("battle.duplicate_level_window") or 5)
        except (TypeError, ValueError):
            window = 5
    species_id = caught.get("id")
    shiny = bool(caught.get("shiny"))
    owned = [p for p in (ankimon_db.get_all_pokemon() or [])
             if p and p.get("id") == species_id and bool(p.get("shiny")) == shiny]
    if not owned:
        return True, None, "first shiny" if shiny else "new species"
    best = max(owned, key=lambda p: (int(p.get("level") or 0), _average_iv(p)))
    wild_lv = int(caught.get("level") or 0)
    own_lv = int(best.get("level") or 0)
    diff = wild_lv - own_lv
    if diff > window:
        return True, best, "Lv %d -> Lv %d" % (own_lv, wild_lv)
    if abs(diff) <= window:
        wiv, oiv = _average_iv(caught), _average_iv(best)
        if wiv > oiv:
            return True, best, "better IVs (average %.1f vs %.1f)" % (wiv, oiv)
        return False, best, "yours has IVs as good (average %.1f vs %.1f)" % (oiv, wiv)
    return False, best, "yours is higher level (Lv %d vs Lv %d)" % (own_lv, wild_lv)


def is_catch_upgrade(enemy_pokemon):
    """Would catching this wild Pokémon upgrade the copy you own? Used by
    Automatic Battle mode 3 to decide catch vs defeat."""
    try:
        shiny = bool(getattr(enemy_pokemon, "shiny", False))
        if settings_obj.get("battle.replace_duplicate_catches") is False:
            return shiny                      # old behaviour: always catch shinies
        rec = {"id": enemy_pokemon.id, "level": enemy_pokemon.level, "shiny": shiny,
               "iv": dict(getattr(enemy_pokemon, "iv", None) or {})}
        keep, best, _why = _duplicate_verdict(rec)
        # Regular and shiny are separate one-per-species slots, so this is
        # also True for your first regular or first shiny copy.
        return bool(keep)
    except Exception:
        return False


def resolve_duplicate_catch(caught, logger=None):
    """Decide where a newly caught Pokémon should be written.

    Returns the individual_id to save under, or None to release the catch.

    An upgrade reuses your existing individual_id, so a Pokémon in your team
    or set as your buddy keeps its slot. Its held item is returned to the bag;
    moves, EVs, friendship and XP come from the new Pokémon.
    """
    _DUP_NOTE[0] = ""
    try:
        if settings_obj.get("battle.replace_duplicate_catches") is False:
            return caught.get("individual_id")
        keep, best, why = _duplicate_verdict(caught)
        shiny = bool(caught.get("shiny"))
        name = ("shiny " if shiny else "") + str(caught.get("name", "?"))
        if best is None:
            if shiny:
                _DUP_NOTE[0] = "Shiny! Your first shiny %s." % caught.get("name", "?")
            return caught.get("individual_id")          # new species / first shiny
        if not keep:
            _DUP_NOTE[0] = "Released it - %s." % why
            if logger:
                logger.log("info", "Released the wild %s - %s." % (name, why))
            return None
        note = "Upgraded your %s: %s." % (name, why)
        item = best.get("held_item")
        if item:
            try:
                from ..utils import give_item
                give_item(item)
                note += " Its %s went back to your bag." % str(item).replace("-", " ").title()
            except Exception as e:
                if logger:
                    logger.log("error", "could not return held item %s: %s" % (item, e))
        _DUP_NOTE[0] = note
        if logger:
            logger.log("info", note)
        return best.get("individual_id") or caught.get("individual_id")
    except Exception as e:
        if logger:
            try:
                logger.log("error", "duplicate check failed: %s" % e)
            except Exception:
                pass
        return caught.get("individual_id")


def save_caught_pokemon(
    enemy_pokemon: PokemonObject,
    nickname: Union[str, None] = None,
    achievements: Union[dict, None] = None,
):
    # Create a dictionary to store the Pokémon's data
    # add all new values like hp as max_hp, evolution_data, description and growth rate
    if enemy_pokemon.tier is not None and achievements is not None:
        if enemy_pokemon.tier == "Normal":
            check = check_for_badge(achievements, 17)
            if check is False:
                achievements = receive_badge(17, achievements)
        elif enemy_pokemon.tier == "Baby":
            check = check_for_badge(achievements, 18)
            if check is False:
                achievements = receive_badge(18, achievements)
        elif enemy_pokemon.tier == "Ultra":
            check = check_for_badge(achievements, 8)
            if check is False:
                achievements = receive_badge(8, achievements)
        elif enemy_pokemon.tier == "Legendary":
            check = check_for_badge(achievements, 9)
            if check is False:
                achievements = receive_badge(9, achievements)
        elif enemy_pokemon.tier == "Mythical":
            check = check_for_badge(achievements, 10)
            if check is False:
                achievements = receive_badge(10, achievements)

    # enemy_pokemon.stats["xp"] = 0
    enemy_pokemon.xp = 0
    # Use to_dict() so the caught record shares the canonical shape with
    # saved main Pokemon (includes base_stats, level-scaled stats, cp,
    # nature). Then override caught-only fields.
    _max_hp = enemy_pokemon.calculate_max_hp()
    caught_pokemon = enemy_pokemon.to_dict()
    caught_pokemon.update({
        "name": display_name(enemy_pokemon.name),
        "nickname": nickname or "",
        "ev": {"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0},
        "friendship": 0,
        "pokemon_defeated": 0,
        "xp": 0,
        "everstone": False,
        "captured_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "individual_id": str(uuid.uuid4()),
        "mega": False,
        "special_form": None,
        "is_favorite": False,
        "held_item": None,
        "hp": _max_hp,
        "current_hp": _max_hp,
    })
    # Recompute CP against the overridden (zeroed) EVs.
    caught_pokemon["cp"] = calculate_cp_from_dict(caught_pokemon)

    # Resolve against any copy already owned: upgrade in place, or discard.
    _target = resolve_duplicate_catch(caught_pokemon, mw.logger if hasattr(mw, "logger") else None)
    if _target is None:
        return
    caught_pokemon["individual_id"] = _target

    # Save to database (replaces JSON file I/O for performance)
    ankimon_db.save_pokemon(caught_pokemon)

    # If that replaced your buddy, reload the live buddy object. Otherwise the
    # old copy in memory is saved back over the upgrade after the next battle.
    try:
        from ..singletons import main_pokemon as _buddy
        if getattr(_buddy, "individual_id", None) == _target:
            from .update_main_pokemon import update_main_pokemon
            update_main_pokemon(_buddy)
    except Exception as e:
        try:
            mw.logger.log("error", "buddy reload after upgrade failed: %s" % e)
        except Exception:
            pass


def _xp_multiplier(key, default):
    """Read an XP multiplier setting, tolerating blank or junk input."""
    try:
        raw = settings_obj.get(key)
        if raw is None or raw == "":
            return float(default)
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return float(default)


def award_capture_experience(enemy_pokemon, logger, achievements=None):
    """Give the buddy XP for a catch, mirroring the defeat pipeline.

    Runs the same calc_experience / manual-move halving / Lucky Egg / XP Share
    / save_main_pokemon_progress path as kill_pokemon, so level-ups and
    evolution prompts behave identically - only the multiplier differs.
    Returns the experience actually awarded (0 when disabled).
    """
    mult = _xp_multiplier("battle.capture_xp_multiplier", 0.2)
    if mult <= 0:
        return 0
    try:
        # Local imports: singletons imports from this package, so importing at
        # module scope would be circular.
        from ..singletons import main_pokemon, evo_window

        exp = calc_experience(enemy_pokemon.base_experience, enemy_pokemon.level)
        if settings_obj.get("controls.allow_to_choose_moves"):
            exp *= 0.5
        exp *= mult
        exp = max(1, math.ceil(exp))
        # Wild team rotation: final blow keeps 50%, the rest is shared out
        exp = _wild_share_exp(exp, main_pokemon, logger, evo_window)

        xp_share_individual_id = settings_obj.get("trainer.xp_share")
        if xp_share_individual_id:
            exp = xp_share_gain_exp(logger, settings_obj, evo_window,
                                    main_pokemon.id, exp, xp_share_individual_id)

        if main_pokemon.held_item == "lucky-egg":
            exp = int(exp * 1.5)

        main_pokemon.level = save_main_pokemon_progress(
            main_pokemon, enemy_pokemon, exp,
            achievements if achievements is not None else {},
            logger, evo_window,
        )
        return exp
    except Exception as e:
        try:
            logger.log("error", f"capture XP failed: {e}")
        except Exception:
            pass
        return 0


def catch_pokemon(
    enemy_pokemon: PokemonObject,
    ankimon_tracker_obj: AnkimonTracker,
    logger: Union[ShowInfoLogger, None] = None,
    nickname: Union[str, None] = None,
    collected_pokemon_ids: Union[set, None] = None,
    achievements: Union[dict, None] = None,
):
    ankimon_tracker_obj.caught += 1
    # Catching now grants experience too (scaled by its own multiplier).
    _gained = award_capture_experience(enemy_pokemon, logger, achievements)
    if _gained:
        try:
            logger.log("info", f"Gained {_gained} XP for catching "
                               f"{enemy_pokemon.name}.")
        except Exception:
            pass
    if ankimon_tracker_obj.caught > 1:
        if False is True:
            logger.log_and_showinfo(
                "info", translator.translate("already_caught_pokemon")
            )  # Display a message when the Pokémon is caught
            return

    # If we arrive here, this means that ankimon_tracker_obj.caught == 1
    if not nickname:
        nickname = display_name(enemy_pokemon.name)
    if collected_pokemon_ids is not None:
        collected_pokemon_ids.add(enemy_pokemon.id)  # Update cache
    save_caught_pokemon(enemy_pokemon, nickname, achievements)

    ankimon_tracker_obj.general_card_count_for_battle = 0

    msg = translator.translate(
        "caught_wild_pokemon", enemy_pokemon_name=display_name(enemy_pokemon.name)
    )
    if _DUP_NOTE[0]:
        msg += "\n" + _DUP_NOTE[0]          # upgraded / released explanation

    if False is True:
        if logger is not None:
            logger.log_and_showinfo(
                "info", f"{msg}"
            )  # Display a message when the Pokémon is caught

    color = "#a17cf7"  # 6A4DAC" #pokemon leveling info color for tooltip
    try:
        if _wild_popup("catch"):
            tooltipWithColour(msg, color)
    except Exception as e:
        if logger is not None:
            show_warning_with_traceback(
                parent=mw, exception=e, message="Error while catching Pokémon:"
            )  # Display a message when the Pokémon is caught

    pokemon_pc.refresh_pokemon_grid()


def handle_enemy_faint(
    main_pokemon: PokemonObject,
    enemy_pokemon: PokemonObject,
    collected_pokemon_ids: set,
    test_window: TestWindow,
    evo_window: EvoWindow,
    reviewer_obj: Reviewer_Manager,
    logger: ShowInfoLogger,
    achievements: dict,
):
    """
    Handles what automatically happens when the enemy Pokémon faints, based on auto-battle settings.
    """
    try:
        auto_battle_setting = int(settings_obj.get("battle.automatic_battle"))
        if not (0 <= auto_battle_setting <= 3):
            auto_battle_setting = 0  # fallback
    except ValueError:
        auto_battle_setting = 0  # fallback

    # Legendaries (Mewtwo...): beat it = catch it, whatever the battle mode
    try:
        from ..wild import wild_rules as _wild
        if _wild.must_catch(enemy_pokemon):
            auto_battle_setting = 1
    except Exception:
        pass

    if auto_battle_setting == 3:  # Catch if uncollected
        enemy_id = enemy_pokemon.id
        # Check cache instead of file
        # Catch new species, and upgrades of your regular or shiny copy
        # (shinies are their own one-per-species slot, so a first shiny
        # counts - see _duplicate_verdict). Defeat everything else for XP.
        if enemy_id not in collected_pokemon_ids or is_catch_upgrade(enemy_pokemon):
            catch_pokemon(
                enemy_pokemon,
                ankimon_tracker_obj,
                logger,
                "",
                collected_pokemon_ids,
                achievements,
            )
        else:
            kill_pokemon(
                main_pokemon,
                enemy_pokemon,
                evo_window,
                logger,
                achievements,
                trainer_card,
            )
        new_pokemon(
            enemy_pokemon, test_window, ankimon_tracker_obj, reviewer_obj
        )  # Show a new random Pokémon
    elif auto_battle_setting == 1:  # Existing auto-catch
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
        )  # Show a new random Pokémon
    elif auto_battle_setting == 2:  # Existing auto-defeat
        kill_pokemon(
            main_pokemon, enemy_pokemon, evo_window, logger, achievements, trainer_card
        )
        new_pokemon(
            enemy_pokemon, test_window, ankimon_tracker_obj, reviewer_obj
        )  # Show a new random Pokémon

    # For Manual mode (auto_battle_setting == 0): no need to show window or do actions automatically
    test_window.display_pokemon_death()
    main_pokemon.reset_bonuses()
    ankimon_tracker_obj.general_card_count_for_battle = 0


def handle_main_pokemon_faint(
    main_pokemon: PokemonObject,
    enemy_pokemon: PokemonObject,
    test_window: TestWindow,
    reviewer_obj: Reviewer_Manager,
    translator: Translator,
):
    """
    Handles what happens when the main Pokémon faints.
    """
    if _wild_popup("faint"):
        msg = translator.translate(
            "pokemon_fainted", enemy_pokemon_name=display_name(main_pokemon.name)
        )
        tooltipWithColour(msg, "#E12939")
    play_effect_sound(settings_obj, "Fainted")

    # Wild team rotation: the next team member (buddy first, then team slots
    # 1-6) comes in against the SAME wild Pokemon, which keeps its damage.
    try:
        from ..wild import wild_rules as _wild
        outcome = _wild.on_buddy_fainted(main_pokemon, enemy_pokemon)
    except Exception as e:
        print("Ankimon: team rotation failed:", e)
        _wild = None
        outcome = "whiteout"
    if outcome == "next":
        if _wild_popup("faint"):
            tooltipWithColour(f"Go, {display_name(main_pokemon.name)}!", "#F5B041")
        return
    if outcome == "won":            # the wild one fainted on the same turn
        return

    # Whole team fainted: hurry away (counts as fleeing). new_pokemon puts
    # your buddy back in front and heals everyone.
    if _wild_popup("faint"):
        tooltipWithColour("Your team is worn out - you hurried away to rest.", "#F5B041")
    main_pokemon.hp = main_pokemon.max_hp
    main_pokemon.current_hp = main_pokemon.max_hp
    main_pokemon.reset_bonuses()
    if _wild is not None:
        _wild.STATE.block_shiny = True
    try:
        new_pokemon(
            enemy_pokemon, test_window, ankimon_tracker_obj, reviewer_obj
        )  # Show a new random Pokémon
    finally:
        if _wild is not None:
            _wild.STATE.block_shiny = False
