import aqt
from aqt import gui_hooks, mw, utils
from aqt.utils import tooltip

from .singletons import ankimon_tracker_obj, reviewer_obj


def on_show_question(Card):
    ankimon_tracker_obj.start_card_timer()


def on_show_answer(Card):
    ankimon_tracker_obj.stop_card_timer()


def on_reviewer_did_show_question(card):
    reviewer_obj.update_life_bar(mw.reviewer, None, None)


def answerCard_before(filter, reviewer, card):
    utils.answBtnAmt = reviewer.mw.col.sched.answerButtons(card)
    return filter


def answerCard_after(rev, card, ease):
    maxEase = rev.mw.col.sched.answerButtons(card)
    if ease == 1:
        ankimon_tracker_obj.review("again")
    elif ease == maxEase - 2:
        ankimon_tracker_obj.review("hard")
    elif ease == maxEase - 1:
        ankimon_tracker_obj.review("good")
    elif ease == maxEase:
        ankimon_tracker_obj.review("easy")
    else:
        tooltip("Error in ColorConfirmation: Couldn't interpret ease")
    ankimon_tracker_obj.reset_card_timer()


def register_card_hooks():
    gui_hooks.reviewer_did_show_question.append(on_show_question)
    gui_hooks.reviewer_did_show_answer.append(on_show_answer)
    gui_hooks.reviewer_did_show_question.append(on_reviewer_did_show_question)
    aqt.gui_hooks.reviewer_will_answer_card.append(answerCard_before)
    aqt.gui_hooks.reviewer_did_answer_card.append(answerCard_after)
