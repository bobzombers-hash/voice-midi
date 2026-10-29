import pytest

from voice_midi.numbers import normalize_numbers
from voice_midi.parser import ParseError, parse


@pytest.mark.parametrize("text,expected", [
    ("tempo one twenty eight", "tempo 128"),
    ("tempo one hundred twenty eight", "tempo 128"),
    ("eight oh eight kick", "808 kick"),
    ("pad sixteen", "pad 16"),
    ("controller two", "controller 2"),
    ("ninety five", "95"),
    ("Pad 3!", "pad 3"),
    ("third scene", "3 scene"),
])
def test_numbers(text, expected):
    assert normalize_numbers(text) == expected


@pytest.mark.parametrize("text,action,args", [
    ("load 808 kick on pad 3", "load_sound", {"sound": "808 kick", "pad": 3}),
    ("load eight oh eight kick on pad three", "load_sound", {"sound": "808 kick", "pad": 3}),
    ("put the snare on controller two pad 5", "load_sound", {"sound": "snare", "pad": 5, "controller": 2}),
    ("place clap on pad 2 on controller 1", "load_sound", {"sound": "clap", "pad": 2, "controller": 1}),
    ("put clap on pad 2 on the launchpad", "load_sound", {"sound": "clap", "pad": 2, "controller": "launchpad"}),
    ("load vocal chop into track 3 slot 2", "load_sound", {"sound": "vocal chop", "track": 3, "slot": 2}),
    ("arm track 2", "arm_track", {"track": 2}),
    ("disarm track two", "disarm_track", {"track": 2}),
    ("play scene 1", "play_scene", {"scene": 1}),
    ("launch scene four please", "play_scene", {"scene": 4}),
    ("play clip 2 on track 3", "play_clip", {"track": 3, "slot": 2}),
    ("stop", "stop_all", {}),
    ("Stop.", "stop_all", {}),
    ("stop track 4", "stop_track", {"track": 4}),
    ("tempo 128", "tempo", {"bpm": 128.0}),
    ("set tempo to one twenty eight", "tempo", {"bpm": 128.0}),
    ("bpm 174", "tempo", {"bpm": 174.0}),
    ("next preset", "next_preset", {}),
    ("previous patch", "prev_preset", {}),
    ("hit pad 4", "trigger_pad", {"pad": 4}),
    ("trigger pad 4 on controller 2", "trigger_pad", {"pad": 4, "controller": 2}),
    ("play deck 1", "deck_play", {"deck": 1}),
    ("cue 3 on deck 2", "deck_cue", {"cue": 3, "deck": 2}),
    ("switch to logic pro", "set_target", {"target": "logic"}),
    ("use auto pilot", "set_target", {"target": "autopilot"}),
    ("mute track 1", "mute_track", {"track": 1}),
    ("play", "play", {}),
])
def test_parse(text, action, args):
    cmd = parse(text)
    assert cmd.action == action
    assert cmd.args == args


@pytest.mark.parametrize("text", ["", "make it sound better", "tempo 5000", "load on pad"])
def test_parse_errors(text):
    with pytest.raises(ParseError):
        parse(text)
