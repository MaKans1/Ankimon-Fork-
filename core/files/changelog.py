from typing import Union

from aqt import mw
from aqt.operations import QueryOp
from aqt.utils import showWarning
import markdown

from .resources import addon_ver, addon_dir
from .utils import read_github_file, read_local_file, compare_files, write_local_file
from .gui_entities import UpdateNotificationWindow
from .pyobj.error_handler import show_warning_with_traceback
from .pyobj.help_window import HelpWindow

update_infos_md = addon_dir / "updateinfos.md"


# Ankimon 2.0: news comes from this project's repo. It's shown once whenever
# it differs from the local updateinfos.md (i.e. when new notes are published).
NEWS_URL = "https://raw.githubusercontent.com/MaKans1/Ankimon-Fork-/main/core/files/updateinfos.md"


def download_changelog():
    try:
        return read_github_file(NEWS_URL)
    except Exception as e:
        return e


def check_and_show_changelog(online_connectivity: bool, ssh: bool, no_more_news: bool):
    if not (online_connectivity and ssh):
        return

    def done(result: Union[Exception, str, None]):
        if isinstance(result, Exception) or result is None:
            return          # offline or not reachable: no news, no warning
        local_content = read_local_file(update_infos_md)
        if not compare_files(local_content, result):
            write_local_file(update_infos_md, result)
            dialog = UpdateNotificationWindow(markdown.markdown(result))
            if not no_more_news:
                dialog.exec()

    QueryOp(
        parent=mw,
        op=lambda _col: download_changelog(),
        success=done,
    ).without_collection().run_in_background()


def open_help_window(online_connectivity):
    try:
        help_dialog = HelpWindow(online_connectivity)
        help_dialog.exec()
    except Exception as e:
        show_warning_with_traceback(
            parent=mw, exception=e, message="Error in opening Help Guide:"
        )
