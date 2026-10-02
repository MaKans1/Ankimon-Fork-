#!/usr/bin/env python3
"""
Build Ankimon 2.0 from the core plus the packages you want.

    python build.py                          # everything
    python build.py --packages gyms,wild     # pick packages
    python build.py --list                   # what's available

Writes dist/Ankimon/ (the add-on folder) and dist/Ankimon-2.0.ankiaddon
(double-click it, or Anki > Tools > Add-ons > Install from file).
Needs only Python 3.8+; nothing is downloaded.
"""
import argparse
import json
import os
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(HERE, "core", "files")
PACKAGES = os.path.join(HERE, "packages")
DIST = os.path.join(HERE, "dist")


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


def main():
    pk = load_packages()
    ap = argparse.ArgumentParser(description="Build Ankimon 2.0")
    ap.add_argument("--packages", default=",".join(pk),
                    help="comma-separated, default: all (%s)" % ", ".join(pk))
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
    chosen = [p.strip() for p in a.packages.split(",") if p.strip()]
    unknown = [p for p in chosen if p not in pk]
    if unknown:
        sys.exit("Unknown package(s): %s. Try --list." % ", ".join(unknown))
    missing = sorted({r for p in chosen for r in pk[p].get("requires", []) if r not in chosen})
    if missing:
        sys.exit("Also needed: %s (add them to --packages)." % ", ".join(missing))
    for p in chosen:
        for r in pk[p].get("works_better_with", []):
            if r not in chosen:
                print("note: %s works better with %s" % (p, r))

    out = os.path.join(DIST, "Ankimon")
    shutil.rmtree(out, ignore_errors=True)
    copy_tree(CORE, out)
    for p in chosen:
        copy_tree(os.path.join(PACKAGES, p, "files"), out)
    with open(os.path.join(out, "ankimon2_packages.json"), "w", encoding="utf-8") as f:
        json.dump({"packages": chosen}, f, indent=2)

    addon = os.path.join(DIST, "Ankimon-2.0.ankiaddon")
    with zipfile.ZipFile(addon, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(out):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, out))
    print("Built with: core + %s" % (", ".join(chosen) or "no packages"))
    print("  folder:   %s" % out)
    print("  add-on:   %s" % addon)
    if "showdown" in chosen:
        print("Next: python packages/showdown/setup_showdown.py  (once, after installing)")


if __name__ == "__main__":
    main()
