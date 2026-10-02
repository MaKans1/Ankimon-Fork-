import threading
import random
import time

from ..pyobj.ankimon_tracker import AnkimonTracker
from ..addon_files.lib.pypresence import Presence
from aqt.utils import showWarning, tooltip
from aqt import mw
from ..pyobj.error_handler import show_warning_with_traceback
logger = mw.logger

class DiscordPresence:
    def __init__(self, client_id, large_image_url, ankimon_tracker, logger, settings_obj, parent=mw):
        try:
            self.RPC = Presence(client_id)
            self.RPC.connect()
            self.large_image_url = large_image_url
            self.ankimon_tracker: AnkimonTracker = ankimon_tracker
            self.logger_obj = mw.logger
            self.settings = settings_obj
            self.loop = True
            self.start_time = time.time()
            self.thread = None
            self.quotes = [
                "Study hard, your Ankimon is watching!",
                "Ankimon, I choose you—let’s master this deck!",
                "Your knowledge is super effective!",
                "Critical hit! You mastered that concept.",
                "Never give up! Every review gets you closer to evolution.",
                "Your brain gained 50 XP! Keep going!",
                "It’s dangerous to go alone—take your Ankimon deck!",
                "A wild Flashcard appeared! What will you do?",
                "Evolve your knowledge—level up with every session!",
                "Gotta review ‘em all, Ankimon style!"
            ]
            self.state = random.choice(self.quotes)
                    # Check for conflicting addons
            conflicting_addons = check_conflicting_discord_addons()
            if conflicting_addons:
                conflict_list = ', '.join(conflicting_addons)
                logger.log_and_showinfo("warning", f"⚠️ Conflicting Discord Rich Presence addons detected: \n{conflict_list}\n\nPlease remove them to avoid issues with Ankimon's Discord status, or turn off Discord Rich Presence in Ankimon settings :) ")

        except Exception as e:
            logger.log("error",f"Error with Discord setup: {e}")
            tooltip("Error with Discord setup. Is Discord running?")

    def _get_special_quotes(self):
        return [
            f"In battle with {_pname(self.ankimon_tracker.main_pokemon.name)} Lvl {self.ankimon_tracker.main_pokemon.level}",
            f"{_pname(self.ankimon_tracker.main_pokemon.name)} is fired up and ready to fight!",
            f"{_pname(self.ankimon_tracker.main_pokemon.name)} is waiting for your next move!",
            f"The battle is intense, but {_pname(self.ankimon_tracker.main_pokemon.name)} won't back down!",
            f"The stakes are high! {_pname(self.ankimon_tracker.main_pokemon.name)} needs your help to win this fight!",
            f"Victory is within reach for {self.ankimon_tracker.main_pokemon.nickname or _pname(self.ankimon_tracker.main_pokemon.name)}!",
            f"{_pname(self.ankimon_tracker.main_pokemon.name)} is determined to show its strength!",

            f"Keep your guard up! {_pname(self.ankimon_tracker.enemy_pokemon.name)} is no pushover.",
            f"Strategy is key! Plan your moves wisely against {_pname(self.ankimon_tracker.enemy_pokemon.name)}!",
            f"Currently battling {_pname(self.ankimon_tracker.enemy_pokemon.name)} Lvl {self.ankimon_tracker.enemy_pokemon.level}",
            f"The opponent {_pname(self.ankimon_tracker.enemy_pokemon.name)} seems tough—stay sharp!",
            f"Level up and take down {_pname(self.ankimon_tracker.enemy_pokemon.name)}!",

            f"Total reviews completed: {self.ankimon_tracker.get_total_reviews()}",
            f"{self.ankimon_tracker.card_ratings_count['good']} good reviews so far—keep it up!",
            f"You've marked {self.ankimon_tracker.card_ratings_count['again']} cards as Again—let's focus and improve!",
            f"Great job! {self.ankimon_tracker.card_ratings_count['easy']} cards rated Easy!",
            f"{self.ankimon_tracker.card_ratings_count['hard']} cards rated Hard—you're tackling the tough ones!",
        ]

    def update_presence(self):
        """
        Update the Discord Rich Presence with a new state message.
        """
        try:
            while self.loop:
                self.RPC.update(
                    state = random.choice(self.quotes) if int(self.settings.get("misc.discord_rich_presence_text")) == 1 else random.choice(self._get_special_quotes()),
                    large_image=self.large_image_url,
                    start=self.start_time
                )
                time.sleep(30)  # Sleep for 30 seconds before updating again
        except Exception as e:
            logger.log("error",f"Error with Discord Rich Presence: {e}")
            tooltip("Error with Discord Rich Presence. Is Discord running?")

    def start(self):
        """
        Start updating the Discord Rich Presence in a separate thread.
        """
        try:
            if not hasattr(self, 'thread') or self.thread is None or not self.thread.is_alive():
                self.loop = True
                self.thread = threading.Thread(target=self.update_presence, daemon=True)
                self.thread.start()
        except Exception as e:
            logger.log("error",f"Error starting Discord Rich Presence: {e}")
            tooltip("Error starting Discord Rich Presence. Is Discord running?")

    def stop(self):
        """
        Stop updating the Discord Rich Presence.
        """
        try:
            self.loop = False
            if hasattr(self, 'thread') and self.thread and self.thread.is_alive():
                # self.thread.join() # Removed to prevent blocking
                self.thread = None  # Reset the thread
            self.RPC.clear()
        except Exception as e:
            logger.log("error",f"Error clearing Discord Rich Presence: {e}")
            tooltip("Error clearing Discord Rich Presence. Please check Logger for info.")

    def stop_presence(self):
        """
        Update the Discord Rich Presence to indicate a break when stopping.
        """
        try:
            self.loop = False
            if not self.loop:
                self.RPC.update(
                    state="Break time! You’ve earned it.",
                    large_image=self.large_image_url
                )
        except Exception as e:
            logger.log("error",f"Error stopping Discord Rich Presence: {e}")
            tooltip("Error stopping Discord Rich Presence. Please check Logger for info.")

def check_conflicting_discord_addons():
    """
    Check for other Anki addons that may be showing Discord status.
    Returns a list of conflicting addon names if found.
    """
    try:
        from aqt import mw

        # Get list of all installed addons
        addon_manager = mw.addonManager
        installed_addons = addon_manager.allAddons()

        # Known conflicting addon identifiers and names
        conflicting_addons = {
            # Known AnkiCord and Discord addon IDs
            '933207442': 'AnkiCord - Discord Rich Presence (Customized by Shigeඞ)',
            '1133851639': 'AnkiDiscord - Discord integration for Anki',
            '1828536813': 'Ankicord - Discord Rich Presence',
            # Add more known conflicting addon IDs as discovered
        }

        found_conflicts = []

        for addon_id in installed_addons:
            try:
                # Skip if addon is not enabled
                if not addon_manager.isEnabled(addon_id):
                    continue

                # Check against known conflicting addon IDs
                if addon_id in conflicting_addons:
                    addon_name = conflicting_addons[addon_id]
                    found_conflicts.append(addon_name)
                    continue

                # Check addon metadata for potential Discord-related conflicts
                addon_meta = addon_manager.addonMeta(addon_id)
                if addon_meta:
                    addon_name = addon_meta.get('name', '').lower()
                    addon_description = addon_meta.get('description', '').lower()

                    # Keywords that indicate Discord Rich Presence functionality
                    discord_keywords = [
                        'discord', 'ankicord', 'rich presence', 'discord rpc',
                        'discord status'
                    ]

                    # Check if addon name or description contains Discord-related keywords
                    if any(keyword in addon_name for keyword in discord_keywords) or \
                    any(keyword in addon_description for keyword in discord_keywords):
                        display_name = addon_meta.get('name', f'Unknown addon ({addon_id})')
                        found_conflicts.append(display_name)

            except Exception as e:
                # Log but don't fail on individual addon checks
                if hasattr(mw, 'logger') and mw.logger:
                    mw.logger.log("debug", f"Error checking addon {addon_id}: {e}")
                continue

        return found_conflicts

    except Exception as e:
        # Return empty list if checking fails entirely
        if hasattr(mw, 'logger') and mw.logger:
            mw.logger.log("error", f"Error checking for conflicting Discord addons: {e}")
        return []


def _pname(n):
    """Real Pokémon name for display ("Iron Hands", "Mr. Mime")."""
    try:
        from .pokedex_functions import display_name
        return display_name(n)
    except Exception:
        s = str(n or "")
        return s[:1].upper() + s[1:]


def _cap1(s):
    """Capitalise the first letter only (keeps "Iron Hands", "Ho-Oh")."""
    s = str(s or "")
    return s[:1].upper() + s[1:]
