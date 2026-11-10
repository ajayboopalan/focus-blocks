"""Colours and status labels."""

from focusblocks.core.models import Status

# pill and overlay (dark)
INK, TEXT, MUTED, SUB = "#16191e", "#f2f1ee", "#a3abb5", "#c4cad1"
TRACK, LINE, BTN, BTN_HOT, BTN_OFF, OFF_TEXT = "#2e343d", "#2a2f37", "#262b33", "#323843", "#1d2127", "#6b737d"
KEY = "#010203"                       # painted transparent: gives the pill rounded corners
COL = {"focus": "#7cc79a", "test": "#e9b25a", "paused": "#8e99a6", "meeting": "#a897f0",
       "break": "#6db3ee", "wait": "#f07a62", "lunch": "#e89a62"}
STATUS = {  # engine status -> (label, colour key)
    Status.WORKING: ("Focusing", "focus"), Status.MEETING: ("In a meeting", "meeting"),
    Status.AUTO_PAUSED: ("Paused automatically", "paused"), Status.PAUSED: ("Paused", "paused"),
    Status.STOPPED: ("Tracking off", "paused"), Status.GOAL_MET: ("Daily goal reached", "focus"),
    Status.BLOCK_DONE: ("Time for a break", "break"), Status.LUNCH_TIME: ("Lunch time", "lunch"),
    Status.IDLE: ("Ready", "paused"),
    Status.BREAK: ("Break", "break"), Status.WAIT: ("Break over", "wait"), Status.LUNCH: ("Lunch", "lunch"),
}

# settings window (light)
W_BG, W_NAV, W_LINE, W_INK, W_SUB, W_FAINT = "#fbfbfc", "#f1f2f4", "#e1e4e8", "#1c2027", "#4b535e", "#6b737d"
W_GREEN, W_CHECK_OFF, W_SEL_ROW = "#2f7a52", "#b8bec6", "#f2f8f4"
HEAT = ["#ebe8e5", "#f6c7bd", "#ec8f7c", "#d8573f", "#a8301c"]   # heatmap levels 0 (none) .. 4 (goal met)
BADGES = ["#2f6fd0", "#5b5fc7", "#3a6fd8", "#1f6fbf", "#1d8a4a", "#b98a1c", "#a8467a", "#4a7d8c"]
