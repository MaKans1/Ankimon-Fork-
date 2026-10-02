# showdown: changelog

- **Real Game Battle Rules** (setting, on by default): gym and expedition battles run on Pokémon Showdown's simulator (@pkmn/sim). Every move, ability, item, weather, screen, sleep count, two-turn move and one-hit KO behaves as in the main games.
- A small Node.js helper starts when a gym battle opens and stops when it closes. It never touches the network.
- **Expeditions:** a Pokémon can start a fight already damaged, statused or low on PP, so damage carries between floors.
- **Smart leaders** plan a few turns ahead on the simulator: buffs, status and screens when they pay off, attacks when they don't.
- Fixed a crash in the damage estimate with Torrent, Blaze and Overgrow.
- **One-click setup from inside Anki:** the first gym battle offers to download the engine (Node.js plus @pkmn/sim, about 40 MB, checksum-verified) in the background. Works on Windows, macOS and Linux. No Python, npm or command line needed.
- **Fallback:** if the runtime is missing or fails to start, battles use Ankimon's built-in engine automatically.
