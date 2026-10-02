"""
showdown_setup.py - fetches the Showdown battle engine the first time a gym
battle needs it, from inside Anki: no Python, npm or command line for the
player.

Downloads (about 40 MB, once) into user_files/showdown:
  - Node.js (nodejs.org), checked against nodejs.org's SHA-256 list; only the
    node executable is kept
  - Pokémon Showdown's simulator, @pkmn/sim, and its four small dependencies
    (registry.npmjs.org), pinned to the versions the gyms were tuned with

Anki keeps user_files when the add-on is updated, so this happens once.
Part of the showdown package; gym_ui offers it when the engine is missing.
"""
import hashlib
import io
import os
import platform
import shutil
import tarfile
import zipfile
from pathlib import Path

NODE_VERSION = "v24.21.0"
PACKAGES = {                      # exact versions: the gym balance was tuned on these
    "@pkmn/sim": "0.10.11",
    "@pkmn/sets": "5.2.0",
    "@pkmn/streams": "1.1.0",
    "@pkmn/types": "4.0.0",
    "ts-chacha20": "1.2.0",
}
RUNTIME = Path(__file__).resolve().parent.parent / "user_files" / "showdown"
NODE_DIST = "https://nodejs.org/dist/%s/" % NODE_VERSION
NPM = "https://registry.npmjs.org/"

_asked = False      # ask at most once per Anki session
_busy = False


def _fetch(url) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Ankimon"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def node_archive():
    """(archive name, path of the node executable inside it)."""
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    if os.name == "nt":
        top = "node-%s-win-%s" % (NODE_VERSION, arch)
        return top + ".zip", top + "/node.exe"
    plat = "darwin" if platform.system() == "Darwin" else "linux"
    top = "node-%s-%s-%s" % (NODE_VERSION, plat, arch)
    return top + (".tar.gz" if plat == "darwin" else ".tar.xz"), top + "/bin/node"


def _safe_target(root: Path, rel: str) -> Path:
    t = (root / rel).resolve()
    if not str(t).startswith(str(root.resolve())):
        raise RuntimeError("unsafe path in download: %s" % rel)
    return t


def _install_node(data: bytes, name: str, inner: str, dest: Path):
    """Keep only the node executable: node/node.exe or node/bin/node."""
    out = dest / ("node.exe" if os.name == "nt" else os.path.join("bin", "node"))
    out.parent.mkdir(parents=True, exist_ok=True)
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            out.write_bytes(z.read(inner))
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as t:
            f = t.extractfile(inner)
            if f is None:
                raise RuntimeError("node executable missing from %s" % name)
            out.write_bytes(f.read())
        out.chmod(0o755)


def _install_package(data: bytes, dest: Path):
    """An npm tarball (files under package/) -> dest."""
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
        for m in t.getmembers():
            if not m.isfile() or not m.name.startswith("package/"):
                continue
            target = _safe_target(dest, m.name[len("package/"):])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(t.extractfile(m).read())


def install(fetch=_fetch, runtime: Path = RUNTIME):
    """Download and unpack everything. Blocking - run it in the background.
    Builds in a scratch folder and swaps in at the end, so a failed or
    interrupted download never leaves a half-installed engine."""
    tmp = runtime / "_download"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        name, inner = node_archive()
        sums = fetch(NODE_DIST + "SHASUMS256.txt").decode("utf-8", "replace")
        want = next((ln.split()[0] for ln in sums.splitlines() if ln.strip().endswith("  " + name)), None)
        if not want:
            raise RuntimeError("no checksum published for %s" % name)
        data = fetch(NODE_DIST + name)
        if hashlib.sha256(data).hexdigest() != want:
            raise RuntimeError("the Node.js download didn't match its checksum")
        _install_node(data, name, inner, tmp / "node")
        for pkg, ver in PACKAGES.items():
            short = pkg.rsplit("/", 1)[-1]
            _install_package(fetch("%s%s/-/%s-%s.tgz" % (NPM, pkg, short, ver)), tmp / "node_modules" / pkg)
        for d in ("node", "node_modules"):
            shutil.rmtree(runtime / d, ignore_errors=True)
            shutil.move(str(tmp / d), str(runtime / d))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def available() -> bool:
    try:
        from . import gym_showdown
        return gym_showdown.available()
    except Exception:
        return False


def offer():
    """Gym battle starting without the engine: ask (once per session) and
    download in the background. This battle uses the built-in engine unless
    the download finishes while you pick your team."""
    global _asked, _busy
    if _asked or _busy or available() or not (RUNTIME / "bridge.js").exists():
        return
    _asked = True
    from aqt import mw
    from aqt.qt import QMessageBox
    from aqt.utils import tooltip, showWarning
    box = QMessageBox(mw)
    box.setWindowTitle("Real game battle rules")
    box.setText("Gym battles can follow the real games' rules (Pokémon Showdown's battle "
                "simulator). It's a one-time download of about 40 MB.\n\n"
                "Download it now? Until it's ready, gyms use Ankimon's built-in engine.\n\n"
                "(To stop this question: Settings > Gyms > Real Game Battle Rules.)")
    yes = box.addButton("Download", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is not yes:
        return
    _busy = True
    tooltip("Downloading the battle engine in the background...", period=4000)

    def done(fut):
        global _busy
        _busy = False
        try:
            fut.result()
            tooltip("Real game battle rules are ready - they apply from the next gym battle.", period=5000)
        except Exception as e:
            showWarning("Couldn't download the battle engine:\n%s\n\nGym battles keep using the "
                        "built-in engine; you'll be asked again next time you open Anki." % e)

    mw.taskman.run_in_background(install, done)
