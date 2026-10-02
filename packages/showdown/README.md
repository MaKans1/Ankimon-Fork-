# showdown

Runs gym and expedition battles on Pokémon Showdown's simulator: every move, ability and item behaves as in the main games.

**Files**
- `gym/showdown_setup.py`: the one-time download.
- `user_files/showdown/bridge.js` and `gymsim.js`: the battle helper.

**Setup:** nothing to run. The first time a gym battle starts without the engine, Ankimon offers to download it (about 40 MB) in the background:
- Node.js from nodejs.org, checked against nodejs.org's published SHA-256 list (only the `node` program is kept);
- `@pkmn/sim` and its four small dependencies from the npm registry, at the exact versions the gyms were tuned with.

The download goes into `user_files/showdown`, which Anki keeps across add-on updates, so it happens once.

The helper runs only while a gym battle is open and never touches the network.

Needs the **gyms** package. Until the engine is ready, or if it fails, battles use the built-in engine.
