#!/usr/bin/env python3
"""
Build Ankimon 2.0 - for maintainers making a release. Players just download
the files this makes from the Releases page.

    python build.py                          # the release files (below)
    python build.py --packages gyms,wild     # one custom .ankiaddon
    python build.py --list                   # the packages and what they need

Release files, in dist/release:
    Ankimon-2.0.ankiaddon          everything - double-click to install
    Ankimon-2.0-core.ankiaddon     the core only
    Ankimon-2.0-<package>.zip      one per package: unzip and drag its contents
                                   into the Ankimon add-on folder
Needs only Python 3.8+; nothing is downloaded.
"""
import argparse
import json
import os
import shutil
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(HERE, "core", "files")
PACKAGES = os.path.join(HERE, "packages")
DIST = os.path.join(HERE, "dist")
VERSION = "2.0"


def load_packages():
    out = {}
    for name in sorted(os.listdir(PACKAGES)):
        meta = os.path.join(PACKAGES, name, "package.json")
        if os.path.exists(meta):
            with open(meta, encoding="utf-8") as f:
                out[name] = json.load(f)
    return out


def copy_tree(src, dst):
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        rel = os.path.relpath(root, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in files:
            shutil.copy2(os.path.join(root, f), os.path.join(dst, rel, f))


def zip_folder(folder, out_path):
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(folder):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, folder).replace(os.sep, "/"))


def check(pk, chosen):
    unknown = [p for p in chosen if p not in pk]
    if unknown:
        sys.exit("Unknown package(s): %s. Try --list." % ", ".join(unknown))
    missing = sorted({r for p in chosen for r in pk[p].get("requires", []) if r not in chosen})
    if missing:
        sys.exit("Also needed: %s (add them to --packages)." % ", ".join(missing))


def assemble(chosen, out):
    """core + packages -> out (the add-on folder)."""
    shutil.rmtree(out, ignore_errors=True)
    copy_tree(CORE, out)
    for p in chosen:
        copy_tree(os.path.join(PACKAGES, p, "files"), out)
    # stamp the build time: Anki then won't offer AnkiWeb's older Ankimon as an "update"
    man_path = os.path.join(out, "manifest.json")
    with open(man_path, encoding="utf-8") as f:
        man = json.load(f)
    man["mod"] = int(time.time())
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=4)
    with open(os.path.join(out, "ankimon2_packages.json"), "w", encoding="utf-8") as f:
        json.dump({"packages": chosen}, f, indent=2)
    return out


def main():
    pk = load_packages()
    ap = argparse.ArgumentParser(description="Build Ankimon 2.0")
    ap.add_argument("--packages", help="build one .ankiaddon with these (comma-separated)")
    ap.add_argument("--list", action="store_true", help="list packages and exit")
    a = ap.parse_args()
    if a.list:
        for name, m in pk.items():
            print("%-9s %s" % (name, m.get("summary", "")))
            if m.get("requires"):
                print("          requires: %s" % ", ".join(m["requires"]))
            if m.get("works_better_with"):
                print("          works better with: %s" % ", ".join(m["works_better_with"]))
        return

    if a.packages is not None:                       # one custom build
        chosen = [p.strip() for p in a.packages.split(",") if p.strip()]
        check(pk, chosen)
        out = assemble(chosen, os.path.join(DIST, "Ankimon"))
        zip_folder(out, os.path.join(DIST, "Ankimon-%s-custom.ankiaddon" % VERSION))
        print("Built core + %s -> dist/Ankimon-%s-custom.ankiaddon" % (", ".join(chosen) or "nothing", VERSION))
        return

    rel = os.path.join(DIST, "release")
    shutil.rmtree(rel, ignore_errors=True)
    os.makedirs(rel)
    work = os.path.join(DIST, "_work")
    zip_folder(assemble(list(pk), work), os.path.join(rel, "Ankimon-%s.ankiaddon" % VERSION))
    zip_folder(assemble([], work), os.path.join(rel, "Ankimon-%s-core.ankiaddon" % VERSION))
    shutil.rmtree(work, ignore_errors=True)
    for p in pk:
        zip_folder(os.path.join(PACKAGES, p, "files"), os.path.join(rel, "Ankimon-%s-%s.zip" % (VERSION, p)))
    for f in sorted(os.listdir(rel)):
        print("  %-32s %6.1f MB" % (f, os.path.getsize(os.path.join(rel, f)) / 1e6))
    print("Upload these to a GitHub release.")


if __name__ == "__main__":
    main()
