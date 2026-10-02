import copy
import random
from dataclasses import dataclass, field
from typing import Any, Optional

from aqt import mw
from aqt.qt import QDialog

from .singletons import (
    main_pokemon,
    enemy_pokemon,
    settings_obj,
    reviewer_obj,
    ankimon_tracker_obj,
    test_window,
    evo_window,
    logger,
    achievements,
    trainer_card,
    translator,
)
from .functions.encounter_functions import handle_enemy_faint, handle_main_pokemon_faint
from .functions.badges_functions import (
    handle_review_count_achievement,
    check_for_badge,
    receive_badge,
)
from .functions.battle_functions import (
    update_pokemon_battle_status,
    validate_pokemon_status,
    process_battle_data,
)
from .functions.drawing_utils import tooltipWithColour
from .utils import safe_get_random_move, play_effect_sound, play_sound
from .functions.ankimon_hooks_to_poke_engine import simulate_battle_with_poke_engine
from .classes.choose_move_dialog import MoveSelectionDialog
from .pyobj.error_handler import show_warning_with_traceback


@dataclass
class BattleState:
    new_state: Any = None
    mutator_full_reset: int = 1
    user_hp_after: int = 0
    opponent_hp_after: int = 0
    dmg_from_enemy_move: int = 0
    dmg_from_user_move: int = 0
    item_receive_value: int = 0
    collected_pokemon_ids: set = field(default_factory=set)


_state = BattleState()


def init_battle_state(collected_pokemon_ids: set):
    _state.item_receive_value = random.randint(3, 385)
    _state.collected_pokemon_ids = collected_pokemon_ids


def _get_cards_per_round() -> int:
    cards_per_round = settings_obj.get("battle.cards_per_round")
    if isinstance(cards_per_round, int):
        return cards_per_round
    if isinstance(cards_per_round, str) and "-" in cards_per_round:
        try:
            min_val, max_val = map(int, cards_per_round.split("-"))
            return random.randint(min_val, max_val)
        except (ValueError, IndexError):
            return 2
    return 2


def on_review_card(*args):
    global _state
    s = _state

    try:
        # --- gym ladder (optional package) ------------------------------
        try:
            from .gym import gym_ui as _gym
        except ImportError:
            _gym = None
        if _gym is not None:
            _gym.handle_review(ankimon_tracker_obj.get_total_reviews())
            if _gym.gym_is_active():
                return          # a gym battle replaces the wild encounter
        # ----------------------------------------------------------------
        multiplier = ankimon_tracker_obj.multiplier
        # Wild mode: both sides pick moves with the pseudo-smart AI (buff /
        # debuff / status / attack); your Pokemon only uses its ticked moves.
        try:
            from .wild import wild_rules as _wild
        except ImportError:     # Wild Mode package not installed: classic battles
            from .functions import wild_fallback as _wild
        # changed your buddy or team mid-fight? the wild Pokémon flees
        if _wild.check_team_change():
            return
        user_attack, enemy_attack = _wild.choose_moves(main_pokemon, enemy_pokemon, s)

        battle_sounds = settings_obj.get("audio.battle_sounds")

        ankimon_tracker_obj.cards_battle_round += 1
        ankimon_tracker_obj.cry_counter += 1
        cry_counter = ankimon_tracker_obj.cry_counter
        total_reviews = ankimon_tracker_obj.get_total_reviews()
        reviewer_obj.seconds = 0
        reviewer_obj.myseconds = 0
        ankimon_tracker_obj.general_card_count_for_battle += 1

        color = "#F0B27A"

        handle_review_count_achievement(total_reviews, achievements)

        s.item_receive_value -= 1
        if s.item_receive_value <= 0:
            s.item_receive_value = random.randint(3, 385)
            test_window.display_item()
            if not check_for_badge(achievements, 6):
                receive_badge(6, achievements)

        try:
            cash_interval = int(settings_obj.get("trainer.cash_reward_interval", 10))
            cash_amount = int(settings_obj.get("trainer.cash_reward_amount", 100))
        except (ValueError, TypeError):
            cash_interval = 10
            cash_amount = 100
        if cash_interval > 0 and total_reviews % cash_interval == 0:
            from datetime import date
            today_str = str(date.today())
            last_reward_date = settings_obj.get("trainer.last_cash_reward_date", "")
            cash_earned_today = settings_obj.get("trainer.cash_earned_today", 0)
            
            if last_reward_date != today_str:
                cash_earned_today = 0
                settings_obj.set("trainer.last_cash_reward_date", today_str)
            
            if True:                    # no daily cap: every interval pays out
                allowed_amount = cash_amount
                if allowed_amount > 0:
                    settings_obj.set("trainer.cash_earned_today", cash_earned_today + allowed_amount)
                    settings_obj.set("trainer.cash", settings_obj.get("trainer.cash") + allowed_amount)
                    trainer_card.cash = settings_obj.get("trainer.cash")

        if battle_sounds == True and ankimon_tracker_obj.general_card_count_for_battle == 1:
            play_sound(enemy_pokemon.id, settings_obj)

        if ankimon_tracker_obj.cards_battle_round >= _get_cards_per_round():
            ankimon_tracker_obj.cards_battle_round = 0
            ankimon_tracker_obj.attack_counter = 0
            ankimon_tracker_obj.pokemon_encounter += 1
            multiplier = ankimon_tracker_obj.multiplier

            # The enemy attacks every round, regardless of how cards were graded.
            if (
                ankimon_tracker_obj.pokemon_encounter > 0
                and enemy_pokemon.hp > 0
            ):
                enemy_move = _wild.move_details(enemy_attack)
                enemy_move_category = enemy_move.get("category")
                if enemy_move_category == "Status":
                    color = "#F7DC6F"
                elif enemy_move_category == "Special":
                    color = "#D2B4DE"
                else:
                    color = "#F0B27A"
            else:
                enemy_attack = "splash"

            move = _wild.move_details(user_attack)
            category = move.get("category")

            if (
                ankimon_tracker_obj.pokemon_encounter > 0
                and main_pokemon.hp > 0
                and enemy_pokemon.hp > 0
            ):
                if False:   # "Allow Choosing Moves" retired: the Buddy menu's move ticks
                    dialog = MoveSelectionDialog(main_pokemon.attacks)
                    if dialog.exec() == QDialog.DialogCode.Accepted:
                        if dialog.selected_move:
                            user_attack = dialog.selected_move

                if category == "Status":
                    color = "#F7DC6F"
                elif category == "Special":
                    color = "#D2B4DE"
                else:
                    color = "#F0B27A"

            results = simulate_battle_with_poke_engine(
                main_pokemon,
                enemy_pokemon,
                user_attack,
                enemy_attack,
                s.mutator_full_reset,
                s.new_state,
            )

            battle_info = results[0]
            s.new_state = copy.deepcopy(results[1])
            s.dmg_from_enemy_move = results[2]
            s.dmg_from_user_move = results[3]
            s.mutator_full_reset = results[4]
            current_battle_info_changes = results[5]
            instructions = results[0]["instructions"]
            heals_to_user = sum(
                inst[2] for inst in instructions if inst[0:2] == ["heal", "user"]
            )
            heals_to_opponent = sum(
                inst[2] for inst in instructions if inst[0:2] == ["heal", "opponent"]
            )
            true_dmg_from_enemy_move = sum(
                inst[2] for inst in instructions if inst[0:2] == ["damage", "user"]
            )
            true_dmg_from_user_move = sum(
                inst[2] for inst in instructions if inst[0:2] == ["damage", "opponent"]
            )

            if true_dmg_from_enemy_move < 0:
                true_dmg_from_enemy_move = 0
                heals_to_user += abs(true_dmg_from_enemy_move)
            if true_dmg_from_user_move < 0:
                true_dmg_from_user_move = 0
                heals_to_opponent += abs(true_dmg_from_user_move)

            # Wild mode: remember the moves (support-move limit) and hold the
            # wild Pokemon to its healing budget for this encounter.
            heals_to_opponent = _wild.after_turn(s, user_attack, enemy_attack, heals_to_opponent,
                                                 main_pokemon)

            # the engine copy may be fighting at the region's level cap
            _real_hp = _wild.real_hp(main_pokemon, s.new_state.user.active)
            main_pokemon.hp = _real_hp
            main_pokemon.current_hp = _real_hp
            enemy_pokemon.hp = s.new_state.opponent.active.hp
            enemy_pokemon.current_hp = s.new_state.opponent.active.hp

            enemy_status_changed, main_status_changed = update_pokemon_battle_status(
                battle_info, enemy_pokemon, main_pokemon
            )
            enemy_pokemon.battle_status = validate_pokemon_status(enemy_pokemon)
            main_pokemon.battle_status = validate_pokemon_status(main_pokemon)

            formatted_battle_log = process_battle_data(
                battle_info=battle_info,
                multiplier=multiplier,
                main_pokemon=main_pokemon,
                enemy_pokemon=enemy_pokemon,
                user_attack=user_attack,
                enemy_attack=enemy_attack,
                dmg_from_user_move=true_dmg_from_user_move,
                dmg_from_enemy_move=true_dmg_from_enemy_move,
                user_hp_after=main_pokemon.hp,
                opponent_hp_after=enemy_pokemon.hp,
                battle_status=main_pokemon.battle_status,
                pokemon_encounter=ankimon_tracker_obj.pokemon_encounter,
                translator=translator,
                changes=current_battle_info_changes,
            )

            if settings_obj.get("battle.show_battle_popups") is not False:
                tooltipWithColour(formatted_battle_log, color)

            if true_dmg_from_enemy_move > 0:
                reviewer_obj.myseconds = settings_obj.compute_special_variable("animate_time")
                if _wild.popup("damage"):
                    tooltipWithColour(f" -{true_dmg_from_enemy_move} HP ", "#F06060", x=-200)
                play_effect_sound(settings_obj, "HurtNormal")

            if true_dmg_from_user_move > 0:
                reviewer_obj.seconds = settings_obj.compute_special_variable("animate_time")
                if _wild.popup("damage"):
                    tooltipWithColour(f" -{true_dmg_from_user_move} HP ", "#F06060", x=200)
                play_effect_sound(settings_obj, "HurtNormal")
            else:
                reviewer_obj.seconds = 0

            if int(heals_to_user) != 0:
                heal_color = "#68FA94" if heals_to_user > 0 else "#F06060"
                sign = "+" if heals_to_user > 0 else ""
                if _wild.popup("damage"):
                    tooltipWithColour(f" {sign}{int(heals_to_user)} HP ", heal_color, x=-250)

            if int(heals_to_opponent) != 0:
                heal_color = "#68FA94" if heals_to_opponent > 0 else "#F06060"
                sign = "+" if heals_to_opponent > 0 else ""
                if _wild.popup("damage"):
                    tooltipWithColour(f" {sign}{int(heals_to_opponent)} HP ", heal_color, x=250)

            if enemy_pokemon.hp < 1:
                enemy_pokemon.hp = 0
                test_window.display_battle()
                handle_enemy_faint(
                    main_pokemon,
                    enemy_pokemon,
                    s.collected_pokemon_ids,
                    test_window,
                    evo_window,
                    reviewer_obj,
                    logger,
                    achievements,
                )
                s.mutator_full_reset = 1

        if cry_counter == 10 and battle_sounds is True:
            play_sound(enemy_pokemon.id, settings_obj)

        if main_pokemon.hp < 1:
            handle_main_pokemon_faint(
                main_pokemon, enemy_pokemon, test_window, reviewer_obj, translator
            )
            s.mutator_full_reset = 1

        class Container:
            pass

        reviewer = Container()
        reviewer.web = mw.reviewer.web
        reviewer_obj.update_life_bar(reviewer, 0, 0)
        if test_window is not None:
            if enemy_pokemon.hp > 0:
                test_window.display_battle()
    except Exception as e:
        show_warning_with_traceback(
            parent=mw, exception=e, message="An error occurred in reviewer:"
        )
