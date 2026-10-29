"""Command grammar: spoken text -> Command objects.

The grammar is a small set of ordered regexes over number-normalised text.
Fillers ('please', 'the', 'hey') are removed first, so 'put the snare on
controller two pad five please' and 'snare on c2 pad 5' both work.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from .numbers import normalize_numbers

FILLERS = r"\b(please|hey|ok|okay|um|uh|can you|could you|now|the|a|an)\b"


@dataclass
class Command:
    action: str
    args: dict = field(default_factory=dict)
    text: str = ""

    def __getitem__(self, k):
        return self.args[k]


class ParseError(ValueError):
    pass


CTRL = r"(?:(?:on|for|of|in)\s+)?(?:controller|ctrl)\s*(?P<ctrl>\d+|[a-z]+)"
# trailing form also accepts a controller name/alias: 'on launchpad', 'on left'
CTRL_OPT = r"(?:\s+(?:(?:on|for|of|in)\s+)?(?:controller|ctrl)?\s*(?P<ctrl2>\d+|[a-z][a-z0-9 ]*))?"

RULES = [
    # load/put/place <sound> on [controller N] pad N  (controller before or after pad)
    ("load_sound", rf"^(?:load|put|place|assign|drop|set)\s+(?P<sound>.+?)\s+(?:on|onto|to|into|in)\s+(?:{CTRL}\s+)?pad\s+(?P<pad>\d+){CTRL_OPT}$"),
    ("load_sound", rf"^(?:load|put|place|assign|drop)\s+(?P<sound>.+?)\s+(?:on|onto|to|into|in)\s+track\s+(?P<track>\d+)(?:\s+(?:slot|clip)\s+(?P<slot>\d+))?$"),
    ("clear_pad", rf"^(?:clear|empty|remove)\s+pad\s+(?P<pad>\d+){CTRL_OPT}$"),
    ("trigger_pad", rf"^(?:hit|trigger|fire|tap|play)\s+pad\s+(?P<pad>\d+){CTRL_OPT}$"),
    ("play_scene", r"^(?:play|launch|fire|start|trigger)\s+scene\s+(?P<scene>\d+)$"),
    ("play_clip", r"^(?:play|launch|fire|start)\s+clip\s+(?P<slot>\d+)\s+(?:on|of|in)\s+track\s+(?P<track>\d+)$"),
    ("play_clip", r"^(?:play|launch|fire|start)\s+track\s+(?P<track>\d+)\s+clip\s+(?P<slot>\d+)$"),
    ("deck_play", r"^(?:play|start)\s+deck\s+(?P<deck>\d+)$"),
    ("deck_stop", r"^(?:stop|pause)\s+deck\s+(?P<deck>\d+)$"),
    ("deck_cue", r"^(?:cue|hot cue|jump to cue)\s+(?P<cue>\d+)\s+(?:on\s+)?deck\s+(?P<deck>\d+)$"),
    ("arm_track", r"^(?:arm|record arm|rec arm)\s+track\s+(?P<track>\d+)$"),
    ("disarm_track", r"^(?:disarm|unarm)\s+track\s+(?P<track>\d+)$"),
    ("mute_track", r"^mute\s+track\s+(?P<track>\d+)$"),
    ("unmute_track", r"^unmute\s+track\s+(?P<track>\d+)$"),
    ("solo_track", r"^solo\s+track\s+(?P<track>\d+)$"),
    ("select_track", r"^(?:select|go to)\s+track\s+(?P<track>\d+)$"),
    ("stop_track", r"^stop\s+track\s+(?P<track>\d+)$"),
    ("tempo", r"^(?:set\s+)?(?:tempo|bpm)\s+(?:to\s+)?(?P<bpm>\d+(?:\.\d+)?)(?:\s+bpm)?$"),
    ("tempo", r"^(?P<bpm>\d+(?:\.\d+)?)\s+bpm$"),
    ("next_preset", r"^(?:next)\s+(?:preset|patch|sound|program)$"),
    ("prev_preset", r"^(?:previous|prev|last|back)\s+(?:preset|patch|sound|program)$"),
    ("set_target", r"^(?:switch|change|target|use)\s+(?:to\s+)?(?P<target>ableton|live|logic|logic pro|autopilot|auto pilot)$"),
    ("stop_all", r"^(?:stop|stop all|stop everything|halt|panic)$"),
    ("play", r"^(?:play|start|go)$"),
    ("record", r"^(?:record|start recording)$"),
    ("undo", r"^undo$"),
    ("list_pads", r"^(?:list|show)\s+pads$"),
]
COMPILED = [(a, re.compile(p)) for a, p in RULES]
TARGET_NAMES = {"live": "ableton", "logic pro": "logic", "auto pilot": "autopilot"}


def clean(text: str) -> str:
    t = normalize_numbers(text)
    t = t.replace("autopilot", "autopilot").replace("auto pilot", "autopilot")
    t = re.sub(FILLERS, " ", t)
    return re.sub(r"\s+", " ", t).strip(" .")


def parse(text: str) -> Command:
    t = clean(text)
    if not t:
        raise ParseError("empty command")
    for action, rx in COMPILED:
        m = rx.match(t)
        if not m:
            continue
        args = {k: v for k, v in m.groupdict().items() if v is not None}
        for k in ("pad", "track", "slot", "scene", "deck", "cue"):
            if k in args:
                args[k] = int(args[k])
        if "bpm" in args:
            args["bpm"] = float(args["bpm"])
            if not 20 <= args["bpm"] <= 999:
                raise ParseError(f"tempo out of range: {args['bpm']}")
        c = args.pop("ctrl", None) or args.pop("ctrl2", None)
        args.pop("ctrl2", None)
        if c is not None:
            args["controller"] = int(c) if c.isdigit() else c
        if "target" in args:
            args["target"] = TARGET_NAMES.get(args["target"], args["target"])
        if "sound" in args:
            args["sound"] = args["sound"].strip()
        return Command(action, args, text)
    raise ParseError(f"didn't understand: {text!r} (normalised: {t!r})")


def try_parse(text: str) -> Optional[Command]:
    try:
        return parse(text)
    except ParseError:
        return None
