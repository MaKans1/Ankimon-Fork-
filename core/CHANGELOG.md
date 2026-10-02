# Core: general patches (changelog)

Bug fixes and quality-of-life changes on top of Ankimon 2.03. The core is always installed; the big systems (gyms, wild, showdown) are separate packages.

## Names and text
- **Real Pokémon names.** Wild Pokémon used to be named by an internal lookup key, giving "Ironhands", "Jangmoo", "Farfetchd" and "Mr. mime". They're now "Iron Hands", "Jangmo-o", "Farfetch'd" and "Mr. Mime". Saved Pokémon are migrated once.
- **Correct forms.** 15 species used to resolve to an alternate form: every wild Rockruff was Dusk Form, Arceus and Silvally were always Water type, and so on. They're now the base form.
- **"Pokémon"** is spelled the same way in every menu, message and description.
- **Item and Pokédex descriptions** use the newest games' wording. The oldest games' all-caps text ("POKéMON", "POKé BALL") and mid-word line breaks are gone.
- **Move descriptions** match Ankimon's one-on-one battles (112 moves). Examples:
  - Howl now says "Raises the user's Attack by 1."
  - Earthquake says "Double damage on Dig." instead of "Hits adjacent Pokémon…".
  - Moves that need a partner (Helping Hand, Coaching…) say "Fails in a one-on-one battle."
  - Only the text changed; how moves work is untouched.

## Item bag
- Hover an item's sprite or name for its description. The "More Info" button is gone.
- **Items that act directly:** heals and healing berries heal your buddy; cures and status berries cure it; revives bring back a team member who fainted this battle; X items, Dire Hit and Guard Spec boost your buddy for the current battle.
- **Other items:** flavor berries can be fed (+friendship, and EV berries lower that EV); battle berries and held items can be given to hold.
- **No more "Not implemented yet":** items with no use outside battle show a greyed button saying where they work (PP items between expedition floors; Poké Balls aren't needed).
- **Evolution items** list only the Pokémon they evolve. The button is greyed if none qualify, and Pokémon below the level gate are listed but greyed ("Needs Lv 16").
- **Evolution Items Need A Level** (setting, on by default): Lv 16 for a first evolution, Lv 30 for a second.
- **TMs** use the same tiles, with a Teach… screen listing the Pokémon that can learn the move.
- New bag filters: Berries and Battle Items. Long button labels no longer get cut off.

## Mart and cash
- An **Always In Stock** section of basic heals and revives (no Poké Balls).
- No daily cash cap.
- The shop no longer resets the game's random numbers when it restocks.

## Pokémon PC and pickers
- **Search** understands names, nicknames and type words: "fire" lists every Fire type, "fire char" Fire types with "char" in the name. The same search is in the team, XP Share, buddy and item pickers.
- **Can evolve filter:** Pokémon that can evolve right now, by level, by friendship, or with an evolution item in your bag.
- **Sorting** is stable: equal values no longer reshuffle between refreshes, and names sort without regard to case.
- Pressing Enter in the search box only searches; it no longer "clicks" the first Pokémon.

## Catching and EXP
- **Replace Duplicate Catches:** catching a better copy of a species you own replaces yours (same team slot) instead of adding a duplicate. Within the **Duplicate Level Window**, better IVs win; beyond it, the higher level wins.
- Regular and shiny copies are kept separately.
- **EXP multipliers** for defeating and for catching (catches give a share of the defeat EXP).
- Moves learned or forgotten take effect immediately in battle, without restarting Anki.
- Card grades no longer change battle damage.

## Battle screen
- Move buttons and hover cards show type, category, power, accuracy and PP.
- Pop-up messages stack instead of drawing on top of each other.

## New players
- **First start is a short setup:**
  - choose your region (G / Shift+G or the arrow keys to browse) and one of its three starters;
  - then enter your daily card goal, which sets gym pacing and EXP to match.
  - You start in the region you picked, and the game begins right away, with no Anki restart after choosing.
- **What's new:** notes now come from this project, so the confusing "Ankimon Experimental - Version UNKNOWN" popup is gone. Nothing is shown when you're offline.

## Fixes
- **Monthly gift Pokémon** now arrives even if you don't own last month's. Before, the check for last month's Pokémon crashed and nothing was awarded, every time Anki started.

## Settings
- **Goal of Daily Average Cards** drives pacing. Gym intervals and EXP each show "For your goal of N cards a day, recommended: X", and are filled in when you change the goal. The target is about four months to clear all gyms and expeditions at your goal.
- New defaults for the default goal (100 cards a day, 2 cards per round):
  - 225 cards between gyms (was 100);
  - 60 before a rematch (was 100);
  - 40 after "Not now" (was 25);
  - EXP ×4.33 (was ×1.0).
- Short, plain descriptions for every new setting.
- **Retired** (hidden; their values stay in your config):
  - Card Max Time and Styling in Reviewer: nothing read them.
  - Allow Choosing Moves: it popped a dialog every round and halved EXP; the Buddy menu's move ticks replace it.
  - Pop-Up on Defeat: replaced by the Wild Battle Popups toggles.
  - Remove Level Cap: only affected Lv 100.
- "Fight Hotkeys" is now "Hotkeys". The catch/defeat keys apply when Automatic Battle is 0.

## Packages
- The core runs with any combination of packages:
  - without **gyms**, no gyms are offered;
  - without **wild**, wild battles are the classic random-move ones (`functions/wild_fallback.py`).
