"""
voice-midi add-on handler for AbletonOSC (https://github.com/ideoforms/AbletonOSC).

STATUS: prototype, NOT yet tested inside Live. It uses Live's Python Remote
Script API (browser.load_item, DrumPad selection, ClipSlot.create_audio_clip),
which AbletonOSC itself does not expose.

Install:
  1. Copy this file into  .../Remote Scripts/AbletonOSC/abletonosc/voicemidi_handler.py
  2. In AbletonOSC/abletonosc/__init__.py add:   from .voicemidi_handler import VoiceMidiHandler
  3. In AbletonOSC/manager.py, inside init_api(), add  abletonosc.VoiceMidiHandler(self)  to self.handlers
  4. Restart Live. Check Live's Log.txt for "voicemidi" lines.

OSC addresses (all indices 0-based):
  /voicemidi/drumpad/load_browser  track note "Browser Item Name"
  /voicemidi/drumpad/load_file     track note "/abs/path/sample.wav"   (matched by file name in browser)
  /voicemidi/clip_slot/create_audio_clip track slot "/abs/path.wav"    (Live 12+)
"""
import os

import Live

from .handler import AbletonOSCHandler

CATEGORIES = ("drums", "samples", "instruments", "sounds", "user_library", "audio_effects")


class VoiceMidiHandler(AbletonOSCHandler):
    def __init__(self, manager):
        super().__init__(manager)
        self.class_identifier = "voicemidi"

    # -- browser search (breadth-first, capped so a huge library can't hang Live)
    def _find(self, name, limit=20000):
        browser = Live.Application.get_application().browser
        want = name.lower()
        queue = [getattr(browser, c) for c in CATEGORIES if hasattr(browser, c)]
        queue += list(getattr(browser, "user_folders", []))
        seen, partial = 0, None
        while queue and seen < limit:
            item = queue.pop(0)
            seen += 1
            n = item.name.lower()
            stem = os.path.splitext(n)[0]
            if item.is_loadable and (n == want or stem == want):
                return item
            if partial is None and item.is_loadable and want in n:
                partial = item
            queue.extend(item.children)
        return partial

    def _select_pad(self, track_index, note):
        song = self.song
        track = song.tracks[track_index]
        rack = next((d for d in track.devices if d.can_have_drum_pads), None)
        if rack is None:
            raise ValueError("no Drum Rack on track %d" % (track_index + 1))
        song.view.selected_track = track
        song.view.select_device(rack)
        rack.view.selected_drum_pad = rack.drum_pads[note]
        return rack

    def _load_pad(self, params, by_file):
        track_index, note, ref = int(params[0]), int(params[1]), str(params[2])
        name = os.path.basename(ref) if by_file else ref
        item = self._find(os.path.splitext(name)[0] if by_file else name)
        if item is None:
            self.logger.info("voicemidi: no browser item for %s" % ref)
            return ("not_found", ref)
        self._select_pad(track_index, note)
        Live.Application.get_application().browser.load_item(item)
        self.logger.info("voicemidi: loaded %s on note %d" % (item.name, note))
        return ("ok", item.name)

    def _create_audio_clip(self, params):
        t, s, path = int(params[0]), int(params[1]), str(params[2])
        slot = self.song.tracks[t].clip_slots[s]
        if not hasattr(slot, "create_audio_clip"):
            return ("unsupported", "needs Live 12+")
        slot.create_audio_clip(path)
        return ("ok", path)

    def init_api(self):
        self.osc_server.add_handler("/voicemidi/drumpad/load_browser", lambda p: self._load_pad(p, False))
        self.osc_server.add_handler("/voicemidi/drumpad/load_file", lambda p: self._load_pad(p, True))
        self.osc_server.add_handler("/voicemidi/clip_slot/create_audio_clip", self._create_audio_clip)
