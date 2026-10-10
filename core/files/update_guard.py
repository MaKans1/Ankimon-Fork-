"""
update_guard.py - lets Anki update Ankimon while Anki is running (Ankimon 2.5).

Anki updates an add-on by renaming its user_files folder aside, deleting the
add-on folder and unpacking the new version. On Windows that fails while a
file in there is open, and Ankimon keeps its save database
(user_files/ankimon.db) and its log file open the whole session: "Access is
denied" (the rename) or "being used by another process" (the delete).

Right before Anki installs Ankimon (gui_hooks.addon_manager_will_install_addon),
this closes them, the animated sprites' files (Qt keeps a playing GIF open -
the PC box has a page of them) and a Showdown battle helper if one is running.
Nothing is lost - everything is already saved - and Anki asks for a restart
once the update is in. Other add-ons' installs are left alone.
"""
import logging
import os

PACKAGE = __name__.split(".")[0]
ADDON = os.path.dirname(os.path.abspath(__file__))
_installed = [False]


def release_files():
    """Close everything Ankimon holds open inside its add-on folder. Returns
    what was closed (for the log / tests)."""
    done = []
    try:
        from aqt import mw
        db = getattr(mw, "ankimon_db", None)
        if db is not None:
            db.close()
            done.append("database")
    except Exception:
        pass
    # log files under the add-on folder (Ankimon's logger writes pyobj/app.log)
    try:
        root = os.path.normcase(os.path.abspath(ADDON))
        loggers = [logging.getLogger()] + [lg for lg in logging.Logger.manager.loggerDict.values()
                                           if isinstance(lg, logging.Logger)]
        for lg in loggers:
            for h in list(lg.handlers):
                f = getattr(h, "baseFilename", None)
                if f and os.path.normcase(os.path.abspath(f)).startswith(root):
                    try:
                        h.close()
                    finally:
                        lg.removeHandler(h)
                    done.append("log")
    except Exception:
        pass
    # animated sprites: a QMovie keeps its file open while it plays (the PC box
    # builds a grid of them at startup) - stop each one and let go of its file
    try:
        import gc
        from aqt.qt import QApplication, QMovie
        movies = {}
        for o in gc.get_objects():
            if isinstance(o, QMovie):
                movies[id(o)] = o
        for w in QApplication.allWidgets():
            m = getattr(w, "movie", None)          # QLabel.movie(), or a label's own .movie attribute
            try:
                m = m if isinstance(m, QMovie) else (m() if callable(m) else None)
            except Exception:
                m = None
            if isinstance(m, QMovie):
                movies[id(m)] = m
        for m in movies.values():
            try:
                m.stop()
                m.setFileName("")                  # closes the file it was reading
            except Exception:
                pass
        if movies:
            done.append("sprites:%d" % len(movies))
    except Exception:
        pass
    # a running Showdown battle helper (node.exe from user_files/showdown)
    try:
        import gc
        for o in gc.get_objects():
            if type(o).__name__ == "ShowdownBattle" and callable(getattr(o, "close", None)):
                o.close()
                done.append("showdown")
    except Exception:
        pass
    return done


def _will_install(*args):
    """gui_hooks.addon_manager_will_install_addon(manager, module)."""
    try:
        module = str(args[-1]) if args else ""
        if module == PACKAGE:
            release_files()
    except Exception:
        pass


def install():
    """Called once at startup (__init__)."""
    if _installed[0]:
        return
    try:
        from aqt import gui_hooks
        hook = getattr(gui_hooks, "addon_manager_will_install_addon", None)
        if hook is not None:
            hook.append(_will_install)
            _installed[0] = True
    except Exception:
        pass
