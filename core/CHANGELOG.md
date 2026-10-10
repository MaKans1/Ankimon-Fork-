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

## Partner-only moves removed
These moves do nothing in Ankimon's one-on-one battles, or only help the opponent, so no Pokémon learns them any more:
- by level-up, in the wild, or by TM;
- **Removed:** Helping Hand, Ally Switch, Aromatic Mist, Coaching, Dragon Cheer, Hold Hands, Follow Me, Rage Powder, Spotlight, After You, Heal Pulse, Floral Healing, Decorate and Instruct.
- **Your Pokémon that knew one** get the strongest move they could have learned by their level, or keep 3 moves until they learn more.
- **Kept:** moves that also help the user (Howl, Gear Up, Magnetic Flux, Life Dew, screens, guards).

## Catching and the Pokédex
- **Upgrade Behavior** (Settings > Battle, under Replace Duplicate Catches):
  - *Prioritize Level*: the higher level always wins.
  - *Prioritize Average IV*: better IVs win within the Duplicate Level Window, and the higher level wins beyond it.
- **Favorited Pokémon are never replaced** by a catch.
- **Pokémon that evolve in different ways keep one copy per evolution:** Eevee keeps your 8 best, Ralts and Kirlia 2 (Gardevoir and Gallade), Tyrogue 3, Oddish and Gloom 2, and so on (23 species). Until they're full, a new catch is simply kept; after that it replaces your weakest copy if it's better.
- **Evolving registers the new species in the Pokédex straight away** and checks region Pokédex badges.
- **The Pokédex shows what you caught today.** It used to keep showing your collection as it was when Anki started, so new catches and evolutions looked uncaught until a restart.
- **Region buttons filter the Pokédex grid** (All, Caught and Not Caught within that region). Before, they only changed the page count and progress line.
- **Automatic Battle defaults to 3** (catch new species and better copies, otherwise defeat for EXP) for new players.

- **Choose Pokémon Team:** each slot shows its held item; right-click a sprite or name for that Pokémon's moves and held item (forget, remember, TMs).

## Readability
- **Text colour follows the background:** every window that paints its own background (starter screen, evolution, battle popups) now sets a matching text colour, so text is readable in light and dark mode on every system. It was black on black in macOS light mode.
- **First-start popups** (daily goal, "ready!") use Anki's own theme.
- **Item names:** item drops and gym loot use the official names ("Super Potion", "PP Up"), and TM drops name their move ("TM Aerial Ace") instead of a sprite file name.

## Popups
- **Show Item Pickup Popups** (Settings > Battle > Wild Battle Popups, on by default). Off: items you find while reviewing still go into your bag, without the "You received an item" window.

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
- **Ankimon > Other > Packages…** switches gyms, wild and showdown on or off (restart to apply). Your Pokémon and progress are kept either way.
- **One update file for everyone:** updating with the full file keeps the packages you had, including for players who installed only some of them.
- **Help > Update** downloads the newest Ankimon 2.x (Ankimon.ankiaddon) and shows the steps. It used to download the original Ankimon, which would have replaced 2.x. In 2.0 the same button gets 2.5.
- **Updating from inside Anki works:** when Anki installs an Ankimon update, Ankimon first closes its save file and log (on Windows the update used to stop with "Access is denied").
- **New items:** Z-Ring and Z-Crystals (Alola), Dynamax Band (Galar), Tera Orb and Tera Shards (Paldea), Herba Mystica (eat it from the bag) and the four ruinous stakes. Key items have no Use button, and none of these are random drops.
- Package files that live in user_files (badge art, the Showdown helper) now update with the add-on. Before, Anki kept the old copies.
- The core runs with any combination of packages:
  - without **gyms**, no gyms are offered;
  - without **wild**, wild battles are the classic random-move ones (`functions/wild_fallback.py`).
