"""Sprites Ankimon adds to - or corrects in - the downloaded sprite pack (user 2026-10-28).

The sprite pack every player downloads (sprites.zip) has Diggersby's back sprite
drawn at twice the usual pixel size - 160x160 where the rest are 96x96 - so with
static images it showed twice as big as your Pokémon in the reviewer (Sylveon's
spare back sprite in missing_back too). Ankimon ships corrected copies in
addon_sprites/fixed_sprites/ (core_patches/make_sprite_fixes.py), and at startup
each one replaces the downloaded file when they differ: Anki never overwrites
user_files on an update, so this is how the fix reaches every player.

The same folder carries the Mega Evolution sprites (Aronousqui20, with permission) and the
Mega item icons (MBCMechachu and the Item Dex artists) - credited in credits.html.
A file is copied when the pack's copy is missing or differs (a redrawn sprite can keep
its byte size; only same-size files are read and compared).
"""
import os
import shutil

from ..resources import addon_dir, pkmnimgfolder

FIXED = os.path.join(addon_dir, "addon_sprites", "fixed_sprites")


def apply_sprite_fixes(fixed=FIXED, sprites=pkmnimgfolder):
    """Copy the corrected sprites over the pack's; returns how many changed. Never raises."""
    n = 0
    for root, _dirs, files in os.walk(fixed):
        for f in files:
            src = os.path.join(root, f)
            dst = os.path.join(sprites, os.path.relpath(src, fixed))
            try:
                if not os.path.isdir(os.path.dirname(dst)):
                    continue                    # that folder isn't downloaded (yet)
                if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
                    with open(src, "rb") as a, open(dst, "rb") as b:
                        if a.read() == b.read():
                            continue
                shutil.copyfile(src, dst)
                n += 1
            except OSError:
                pass
    return n
