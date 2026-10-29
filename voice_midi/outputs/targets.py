"""DAW / app targets. Each method returns a short human string describing what
happened (or why it can't), so the CLI can speak/print honest feedback."""
import functools
import logging

import mido

from .. import platform_info
from .keys import send_keys

log = logging.getLogger("voice_midi")

MMC = {"play": 0x02, "stop": 0x01, "record": 0x06}


class Target:
    name = "base"

    def __init__(self, cfg, midi_out, osc=None, dry_run=False):
        self.cfg, self.midi, self.osc, self.dry_run = cfg, midi_out, osc, dry_run
        m = cfg.midi
        self.ch = int(m.get("out_channel", 0))
        self.cc = m.get("cc", {})

    # helpers
    def _cc(self, key, value=127, offset=0, channel=None):
        num = self.cc.get(key)
        if num is None:
            return f"no CC configured for {key}"
        self.midi.send(mido.Message("control_change", channel=self.ch if channel is None else channel,
                                    control=int(num) + offset, value=int(value)))
        return f"sent CC{int(num) + offset}={value}"

    def _tempo_cc(self, bpm):
        lo, hi = self.cfg.midi.get("tempo_range", [60, 187])
        v = max(0, min(127, round((bpm - lo) / (hi - lo) * 127)))
        return self._cc("tempo", v)

    def _keystroke(self, key_name, app=None):
        """Optional keyboard shortcut from targets.<name>.key_commands (cross-platform)."""
        kc = self.cfg.target(self.name).get("key_commands") or {}
        combo = platform_info.pick(kc.get(key_name))
        if not kc.get("enabled") or not combo:
            return None
        return send_keys(combo, app=app, dry_run=self.dry_run)

    def unsupported(self, what):
        return f"{self.name}: '{what}' not supported"

    # default implementations (MIDI-only, needs MIDI mapping in the host)
    def tempo(self, bpm): return self._tempo_cc(bpm) + " (map this CC to tempo)"
    def next_preset(self): return self._cc("next_preset")
    def prev_preset(self): return self._cc("prev_preset")
    def arm_track(self, t, on=True): return self._cc("arm_track_base", 127 if on else 0, t - 1)
    def stop_all(self): return self._cc("stop_all")
    def play(self): return self.unsupported("play")
    def record(self): return self.unsupported("record")
    def play_scene(self, s): return self.unsupported("play scene")
    def play_clip(self, t, s): return self.unsupported("play clip")
    def stop_track(self, t): return self.unsupported("stop track")
    def mute_track(self, t, on=True): return self.unsupported("mute")
    def solo_track(self, t): return self.unsupported("solo")
    def select_track(self, t): return self.unsupported("select track")
    def undo(self): return self.unsupported("undo")
    def load_to_pad(self, sound, pad, note): return self.unsupported("load sound")
    def load_to_slot(self, sound, track, slot): return self.unsupported("load into clip slot")
    def deck(self, action, deck, cue=None): return self.unsupported(f"deck {action}")


class AbletonTarget(Target):
    """AbletonOSC (github.com/ideoforms/AbletonOSC) for transport/tracks/scenes;
    MIDI to IAC for pads. Loading by name uses the custom handler in extras/."""
    name = "ableton"

    def tempo(self, bpm):
        self.osc.send_message("/live/song/set/tempo", [float(bpm)])
        return f"tempo {bpm:g}"

    def play(self):
        self.osc.send_message("/live/song/start_playing", [])
        return "play"

    def stop_all(self):
        self.osc.send_message("/live/song/stop_all_clips", [])
        self.osc.send_message("/live/song/stop_playing", [])
        return "stopped all clips + transport"

    def record(self):
        self.osc.send_message("/live/song/set/record_mode", [1])
        return "arrangement record on"

    def play_scene(self, s):
        self.osc.send_message("/live/scene/fire", [s - 1])
        return f"scene {s} fired"

    def play_clip(self, t, s):
        self.osc.send_message("/live/clip_slot/fire", [t - 1, s - 1])
        return f"clip {s} on track {t} fired"

    def stop_track(self, t):
        self.osc.send_message("/live/track/stop_all_clips", [t - 1])
        return f"track {t} stopped"

    def arm_track(self, t, on=True):
        self.osc.send_message("/live/track/set/arm", [t - 1, 1 if on else 0])
        return f"track {t} {'armed' if on else 'disarmed'}"

    def mute_track(self, t, on=True):
        self.osc.send_message("/live/track/set/mute", [t - 1, 1 if on else 0])
        return f"track {t} {'muted' if on else 'unmuted'}"

    def solo_track(self, t):
        self.osc.send_message("/live/track/set/solo", [t - 1, 1])
        return f"track {t} soloed"

    def select_track(self, t):
        self.osc.send_message("/live/view/set/selected_track", [t - 1])
        return f"track {t} selected"

    def undo(self):
        self.osc.send_message("/live/song/undo", [])
        return "undo"

    # next/prev preset: no AbletonOSC call for browser hot-swap -> MIDI CC (map in Live)
    def next_preset(self): return self._keystroke("next_preset") or self._cc("next_preset") + " (MIDI-map to a device's preset/chain selector)"
    def prev_preset(self): return self._keystroke("prev_preset") or self._cc("prev_preset") + " (MIDI-map to a device's preset/chain selector)"

    def load_to_pad(self, sound, pad, note):
        track = int(self.cfg.target("ableton").get("drum_rack_track", 1))
        if sound.browser:
            self.osc.send_message("/voicemidi/drumpad/load_browser", [track - 1, note, sound.browser])
        elif sound.file:
            self.osc.send_message("/voicemidi/drumpad/load_file", [track - 1, note, sound.file])
        else:
            return f"'{sound.name}' has no browser item or file"
        return (f"asked Live to load '{sound.name}' into the Drum Rack pad for note {note} on track {track} "
                "[needs extras/voicemidi_handler.py in AbletonOSC]")

    def load_to_slot(self, sound, track, slot):
        if not sound.file:
            return f"'{sound.name}' has no file; clip slots need an audio file"
        self.osc.send_message("/voicemidi/clip_slot/create_audio_clip", [track - 1, slot - 1, sound.file])
        return f"asked Live to put '{sound.name}' in track {track} slot {slot} [Live 12+, extras handler]"


class LogicTarget(Target):
    """Logic has no public remote API. We use: MIDI notes (pads), MMC (transport),
    CCs you bind in Controller Assignments, and optional AppleScript keystrokes."""
    name = "logic"

    def _mmc(self, cmd):
        if not self.cfg.target("logic").get("use_mmc", True):
            return None
        self.midi.send(mido.Message("sysex", data=[0x7F, 0x7F, 0x06, MMC[cmd]]))
        return f"MMC {cmd}"

    def _keystroke(self, key_name, app="Logic Pro"):
        return super()._keystroke(key_name, app=app)

    def play(self): return self._mmc("play") or self.unsupported("play")
    def stop_all(self): return (self._mmc("stop") or "") + "; " + self._cc("stop_all")
    def record(self): return self._mmc("record") or self.unsupported("record")
    def next_preset(self): return self._keystroke("next_preset") or self._cc("next_preset") + " (bind in Controller Assignments)"
    def prev_preset(self): return self._keystroke("prev_preset") or self._cc("prev_preset") + " (bind in Controller Assignments)"
    def arm_track(self, t, on=True): return self._cc("arm_track_base", 127 if on else 0, t - 1) + f" (bind to Record Enable track {t})"
    def tempo(self, bpm): return self._tempo_cc(bpm) + " (LIMITED: Logic can't reliably take tempo from MIDI; bind CC or set by hand)"

    def load_to_pad(self, sound, pad, note):
        return (f"LIMITED: Logic can't load samples remotely. This pad now plays note {note}; "
                f"drag '{sound.file or sound.name}' onto that Drum Machine Designer / Quick Sampler pad once.")

    def play_scene(self, s):
        return self.unsupported("play scene") + " (Live Loops: bind Controller Assignment to 'Trigger Scene' manually)"


LOGIC_MAC_ONLY = ("Logic Pro is macOS-only, so the Logic target is off on this PC "
                  "(nothing was sent). Use 'switch to ableton' or 'switch to autopilot'.")


def _mac_only(fn):
    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        if platform_info.current() != "mac":
            return LOGIC_MAC_ONLY
        return fn(self, *a, **kw)
    return wrapper


# Every action on LogicTarget (inherited or overridden) is blocked off-Mac, so
# MMC sysex, CCs and osascript keystrokes never fire on Windows/Linux.
for _n in [n for n in dir(Target) if not n.startswith("_") and callable(getattr(Target, n)) and n != "unsupported"]:
    setattr(LogicTarget, _n, _mac_only(getattr(LogicTarget, _n)))


class AutoPilotTarget(Target):
    """AUTO/PILOT OSC API (autopilot.audio/docs/osc-control): default UDP 9090,
    addresses start /AutoPilot/, one argument per message."""
    name = "autopilot"

    def tempo(self, bpm):
        self.osc.send_message("/AutoPilot/Header/BPM", [float(bpm)])
        return f"AUTO/PILOT BPM {bpm:g}"

    def deck(self, action, deck, cue=None):
        if action == "play":
            self.osc.send_message(f"/AutoPilot/Deck/{deck}/Playing", [1])
        elif action == "stop":
            self.osc.send_message(f"/AutoPilot/Deck/{deck}/Playing", [0])
        elif action == "cue":
            self.osc.send_message(f"/AutoPilot/Deck/{deck}/Cue{cue}", [1])
        return f"AUTO/PILOT deck {deck} {action}{'' if cue is None else ' ' + str(cue)}"

    def play(self): return self.deck("play", 1)
    def stop_all(self):
        for d in (1, 2, 3, 4):
            self.osc.send_message(f"/AutoPilot/Deck/{d}/Playing", [0])
        return "AUTO/PILOT all decks stopped"

    def load_to_pad(self, sound, pad, note):
        return ("AUTO/PILOT: loading by name isn't in the public OSC docs we checked; "
                f"pad {pad} sends MIDI you can MIDI-learn to a sampler slot.")


TARGETS = {"ableton": AbletonTarget, "logic": LogicTarget, "autopilot": AutoPilotTarget}
