# voice-midi — say it instead of clicking it

Prototype (v0.3) of a voice-controlled MIDI controller bridge for **macOS and Windows**.
Say *"load 808 kick on pad 3"*, *"put the snare on controller two pad five"*,
*"arm track 2"*, *"play scene one"*, *"tempo one twenty eight"*, *"next preset"*, *"stop"* —
and it drives **Ableton Live**, **Logic Pro** or **AUTO/PILOT**, while your two hardware
controllers' pads are re-routed and lit to match.

```
 mic ─► speech backend (text | Vosk | faster-whisper, push-to-talk)
         └─► parser (grammar + number words) ─► engine (pad map, target, LEDs)
                                                   ├─► MIDI  → IAC Driver (Mac) / loopMIDI (Windows) ─► Live / Logic / AUTO/PILOT
                                                   ├─► OSC   → AbletonOSC (Live)  /  AUTO/PILOT :9090
                                                   └─► LEDs  → controller 1 + controller 2
 controller pads ─► engine ─► IAC (remapped notes, so both controllers can play one Drum Rack)
```

## What works today vs. what's limited

| Area | Status |
|---|---|
| Command parser (number words, fillers, controller names, fuzzy sound names) | ✅ works, unit-tested |
| Dry-run mode (prints every MIDI/OSC message) | ✅ works |
| Controller profiles (Push 2/3, Launchpad X / Mini MK3, APC40 MkII, APC mini MK2, MPK Mini, Maschine) | ✅ load + pad maps; ⚠️ **not yet verified on hardware** (`verified: false` in each file) |
| Pad forwarding controller → IAC + LED feedback | ✅ code done; ⚠️ needs real-hardware check (colours/port names) |
| Ableton transport/tempo/scenes/clips/arm/mute/solo/select/undo via AbletonOSC | ✅ uses documented AbletonOSC addresses |
| Ableton *load sound into Drum Rack pad / clip slot by name* | ⚠️ **prototype** — needs `extras/voicemidi_handler.py` added to AbletonOSC; untested in Live |
| Ableton "next preset" | ⚠️ sends CC 102/103; you MIDI-map it (e.g. to a Rack chain selector) |
| Logic transport (play/stop/record) | ✅ via MMC, once "Listen to MMC input" is on |
| Logic pads | ✅ notes arrive on IAC; you load the sample into Drum Machine Designer/Quick Sampler once |
| Logic load-by-voice, tempo, scenes | ❌ **Logic has no public remote API.** We send CCs you bind with Controller Assignments, or optional AppleScript keystrokes. Tempo by voice is not reliable. |
| AUTO/PILOT tempo, deck play/stop, hot cues | ✅ OSC (`/AutoPilot/Header/BPM`, `/AutoPilot/Deck/N/Playing`, `/AutoPilot/Deck/N/CueN`) — untested against the app |
| AUTO/PILOT load sample by name | ❌ not in the OSC docs we found; pads send MIDI you can MIDI-learn |
| Windows support (loopMIDI, %APPDATA% config/state, run.bat/run.ps1, Logic auto-disabled) | ✅ code + simulated-Windows tests; ⚠️ **not yet run on a real Windows PC** |
| Speech: Vosk / faster-whisper push-to-talk | ⚠️ code done, lazy-loaded, untested with a mic (only text input was tested) |

## Install on macOS  (Windows: see [Windows setup](#windows-setup))

```bash
brew install python@3.12 portaudio          # portaudio only needed for the microphone
cd voice-midi
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt               # mido, pyyaml, python-rtmidi, python-osc, pytest
pytest -q                                     # should be all green
python -m voice_midi --dry-run                # type commands; nothing is sent anywhere
```

Speech (optional, pick one):

```bash
pip install sounddevice numpy vosk
mkdir -p ~/models && cd ~/models && curl -LO https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip && unzip vosk-model-small-en-us-0.15.zip
python -m voice_midi --speech vosk            # Enter = start talking, Enter = stop

pip install sounddevice numpy faster-whisper  # downloads the model (~150 MB for base.en) on first run
python -m voice_midi --speech whisper
```

macOS will ask for **Microphone** permission for your terminal the first time.
Vosk is restricted to the command vocabulary + your sound names, which makes it accurate for short commands.

## 1. Enable the IAC Driver (virtual MIDI cable)

1. Open **Audio MIDI Setup** → *Window → Show MIDI Studio*.
2. Double-click **IAC Driver**, tick **Device is online**, keep port **Bus 1**, Apply.
3. `python -m voice_midi --list-ports` should now show `IAC Driver Bus 1`.
   (If the name differs, set `midi.out_port` in `config/config.yaml`.)

## 2. Your two controllers

Edit `config/config.yaml`:

```yaml
controllers:
  - id: launchpad_x      # "controller 1", also "left"
    aliases: [left]
  - id: push2            # "controller 2", also "right"
    aliases: [right]
```

Any profile id from `config/controllers/` works. Pads are re-sent to IAC as
`note = 36 + (controller-1)*32 + (pad-1)` — so controller 1 pads 1-32 = notes 36-67,
controller 2 = notes 68-99, and both can play **one** Drum Rack. Set `per_controller_channel: true`
to put each controller on its own MIDI channel instead.

Controller tips:
* **Push 2/3**: press **User** so Live's Push script releases the pads; we use the "User Port".
* **Launchpad X / Mini MK3**: we send the Programmer-mode sysex on start.
* **APC40 MkII / APC mini MK2**: if Live's APC script is active it will also light pads — set the
  control surface to *None* for the controller you want voice-midi to own.
* **MPK Mini**: pads have no host-controllable LEDs; pads default to channel 10.
* **Maschine**: use MIDI mode (Shift+Channel on MK3) or a Controller Editor template.

## 3. Ableton Live

**Pads**: create a MIDI track with a Drum Rack, input = *IAC Driver (Bus 1)*, Monitor = *In*.
In *Settings → Link, Tempo & MIDI* enable **Track** (and **Remote** for MIDI-mapping) for the IAC input.
Don't also enable *Track* for your physical controllers' inputs on that track, or pads will double-trigger.

**AbletonOSC** (deeper control):
1. Download https://github.com/ideoforms/AbletonOSC (Code → Download ZIP), rename the folder to `AbletonOSC`.
2. Move it to `~/Music/Ableton/User Library/Remote Scripts/`.
3. Live → *Settings → Link, Tempo & MIDI* → Control Surface: **AbletonOSC**. Live shows "AbletonOSC: Listening for OSC on port 11000".
4. **Voice loading add-on (prototype)**: copy `extras/voicemidi_handler.py` into
   `Remote Scripts/AbletonOSC/abletonosc/`, then follow the 3 lines at the top of that file. Restart Live.
   Now "load 808 kick on pad 3" searches Live's browser for the `browser:` name in your sound alias
   and loads it into that Drum Rack pad (track set by `targets.ableton.drum_rack_track`).
   "load vocal chop into track 3 slot 2" creates an audio clip from the `file:` (Live 12+).

**Next/previous preset**: Cmd+M in Live, say "next preset" (sends CC 102 on IAC) → click the control to map.

## 4. Logic Pro (honest limits)

Logic has **no public API** for loading samples or patches from outside, so voice-midi does what's possible:

* **Pads**: create a Drum Machine Designer or Quick Sampler (Slice/Drum) track; Logic takes all MIDI inputs
  by default, so IAC notes play it. "load 808 kick on pad 3" records the assignment, lights the pad,
  and tells you which note (e.g. 38) — drag the sample onto that DMD pad once; it's then saved with the project.
* **Transport**: *Logic Pro → Settings → Synchronization → MIDI* → tick **Listen to MMC Input**.
  "play", "stop", "record" then work.
* **Arm / next preset / tempo**: *Logic Pro → Control Surfaces → Controller Assignments* (Expert view),
  click **Learn**, select e.g. *Track 2 Record Enable* or *Next Patch*, then say the command so its CC arrives.
  CCs used: next 102, previous 103, arm track N = 20+N-1, tempo 104, stop-all 105 (all configurable).
* **Key commands** (optional): set `targets.logic.key_commands.enabled: true` and fill in keys you've
  assigned in *Logic → Key Commands*. Grant your terminal **Accessibility** permission
  (System Settings → Privacy & Security). The defaults are placeholders, not Logic's real shortcuts.
* **Not possible right now**: voice tempo that reliably follows (bind it or set by hand), scenes outside
  Live Loops, loading a sound by name.

## 5. AUTO/PILOT notes

A quick lookup of the official docs (https://autopilot.audio/docs/osc-control) shows AUTO/PILOT is
controlled by **OSC and MIDI-mapping**: enable the OSC server in *Settings → OSC* (default UDP **9090**,
feedback on 9096); addresses start with `/AutoPilot/`, one argument per message, e.g.
`/AutoPilot/Header/BPM 128.0`, `/AutoPilot/Deck/1/Playing 1`, `/AutoPilot/Deck/1/Cue1 1`.
⚠️ Those docs describe AUTO/PILOT as a deck/mixer/sampler performance app rather than a Max for Live device — 
if the version you use is a Max for Live device, send me its OSC/MIDI mapping and I'll adjust `AutoPilotTarget`.

Say "switch to autopilot", then "tempo 126", "play deck 2", "stop deck 2", "cue 3 on deck 1".
Pads still go to IAC, so you can MIDI-learn them to AUTO/PILOT's sampler or anything else.

## Windows setup

Logic Pro is Mac-only, so on Windows the targets are **Ableton Live** and **AUTO/PILOT**. Saying
"switch to logic" just answers *"Logic Pro is macOS-only…"* and sends nothing.

**1. Python (x64).** Use **Python 3.12**: `python-rtmidi` currently ships Windows wheels only up to
3.12 (on 3.13 pip would try to compile it and need Visual Studio Build Tools). Vosk, faster-whisper
and python-rtmidi have no Windows-on-ARM wheels, so use an x64 PC.
```powershell
winget install -e --id Python.Python.3.12      # or the installer from python.org (tick "Add python.exe to PATH")
```

**2. Virtual MIDI port: loopMIDI.** Windows has no built-in IAC Driver, and rtmidi can't create virtual ports on Windows.
Install **loopMIDI** (https://www.tobias-erichsen.de/software/loopmidi.html), start it, then type a port name and click **+**.
The app looks for `loopMIDI Port` by default. If you name the port something else (e.g. `VoiceMIDI`), set it in `config.yaml`:
```yaml
midi:
  out_port: {mac: "IAC Driver Bus 1", windows: "VoiceMIDI"}
```
Matching is case-insensitive and by substring, because Windows often lists the port as e.g. `loopMIDI Port 1`. If the port is
missing, the app stops with a clear error that lists the ports it found and how to create the missing one.
Keep loopMIDI running, and tick "Autostart" in its tray menu.

**3. Install + run.**
```powershell
cd voice-midi
py -3.12 -m venv .venv
.venv\Scripts\activate            # PowerShell: .venv\Scripts\Activate.ps1 (if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned)
pip install -r requirements.txt
pytest -q
python -m voice_midi --dry-run
python -m voice_midi --list-ports
```
Or double-click / run **`run.bat --dry-run`** (cmd) or **`.\run.ps1 --dry-run`** (PowerShell). Both create `.venv` and install
requirements the first time, then pass any arguments through.

**4. ⚠️ Windows MIDI ports are exclusive.** On Windows, only one app can open a MIDI port at a time. If Ableton has your
Launchpad/Push open, voice-midi can't read its pads or light its LEDs, and you'll get a warning saying so. Workarounds:
* **Recommended:** in *Ableton → Options → Preferences → Link, Tempo & MIDI*, set the controller's **Control Surface to None**
  and turn its **Input Track/Remote Off** (and Output Off, so the LEDs belong to voice-midi). Turn **Track + Remote On for
  the loopMIDI input**. voice-midi owns the controllers and passes every pad hit through loopMIDI, so Live still hears the pads.
  You give up Live's native Push/APC script for that controller while voice-midi is running.
* **Alternative:** route with MIDI-OX (or loopMIDI plus a MIDI router such as MIDI-OX's *Port Routings*) so one app opens the
  hardware and forwards copies to two loopMIDI ports: one for Live, one for voice-midi.
  Then set the profile's `port_match` to that loopMIDI port.
* Windows port names differ from macOS. Launchpads show `LPX MIDI` plus `MIDIIN2 (LPX MIDI)`, and Push shows `Ableton Push 2`
  plus `MIDIIN2 (Ableton Push 2)`. Run `--list-ports` and adjust `port_match` in the profile if the wrong one is picked.
  For Push, voice-midi needs the *User* port (usually the `MIDIIN2 (...)` one).

**5. AbletonOSC on Windows.** Download https://github.com/ideoforms/AbletonOSC, rename the folder to `AbletonOSC`, and put it in
`%USERPROFILE%\Documents\Ableton\User Library\Remote Scripts\` (create `Remote Scripts` if it doesn't exist). Then go to
*Preferences → Link, Tempo & MIDI → Control Surface: AbletonOSC*. The optional `extras\voicemidi_handler.py` installs the
same way as on Mac. Windows Firewall may ask about Live/Python the first time; OSC uses localhost UDP 11000/11001, so "Private networks" is enough.

**6. AUTO/PILOT on Windows.** The app talks to AUTO/PILOT over OSC on `127.0.0.1:9090` (enable it in *Settings → OSC*), the same as
on Mac. Check that your AUTO/PILOT build runs on Windows; we haven't confirmed a Windows release. MIDI-learn in AUTO/PILOT
should use the **loopMIDI** port. The exclusive-port rule above applies to AUTO/PILOT too.

**7. Speech on Windows.** All the wheels are prebuilt for Windows x64 (checked on PyPI: vosk 0.3.45 `win_amd64`,
sounddevice 0.5.x bundles PortAudio so no separate install is needed, ctranslate2 4.x for faster-whisper has wheels for cp310–cp313):
```powershell
pip install sounddevice numpy vosk             # then unzip a model to C:\Users\you\models\vosk-model-small-en-us-0.15
pip install sounddevice numpy faster-whisper   # CPU int8 works out of the box; NVIDIA GPU needs CUDA 12 + cuDNN (not required)
python -m voice_midi --speech vosk
```
`~` in config paths works on Windows (it means `C:\Users\you`). Allow microphone access for desktop apps under
*Settings → Privacy & security → Microphone*.

**8. Keyboard shortcuts (optional).** `targets.ableton.key_commands` can send shortcuts. On Windows this needs `pip install pynput`,
and the shortcut goes to the focused window. On Mac it uses `osascript`, which needs Accessibility permission. The shortcuts in the config are placeholders.

## Where config and state live

| OS | Per-user dir (state.json, optional config.yaml, extra controllers/) |
|---|---|
| Windows | `%APPDATA%\voice-midi\` |
| macOS | `~/Library/Application Support/voice-midi/` |
| Linux | `~/.config/voice-midi/` |

`python -m voice_midi --init-config` copies the bundled config there so you can edit it outside the app folder.
The lookup order is: `--config` path → `VOICE_MIDI_CONFIG` env var → per-user `config.yaml` → bundled `config/config.yaml`.
Controller profiles in the per-user `controllers\` folder add to (or override) the built-in ones.
(v0.1 stored state in `~/.voice-midi/`; move `state.json` across if you want to keep your old pad assignments.)

## Automatic updates

Installed copies keep themselves current from the GitHub Releases of
[`bobzombers-hash/voice-midi`](https://github.com/bobzombers-hash/voice-midi).

**How it works**
1. **Check** (at launch, at most once per `check_interval_hours`, default 24): one unauthenticated call to
   `api.github.com/repos/bobzombers-hash/voice-midi/releases/latest` with a 4-second timeout. If you're offline,
   rate-limited (60 requests/hour per IP) or there's no release yet, it says so in one line and carries on.
2. **Download + verify**: the release's `voice-midi-X.Y.Z.zip` is checked against the release's `SHA256SUMS`.
   A mismatch is rejected. The files are unpacked to the per-user dir (`…/voice-midi/updates/staged/`).
   **Your running copy is not touched.**
3. **Install on the next launch, never mid-session**: `run.bat`, `run.ps1`, `run.sh` (and `python -m voice_midi`) first run
   the update step from a **temp-dir copy of the updater**, so nothing in the app folder is executing while files are swapped.
   `run.bat` also re-launches itself from `%TEMP%`, because cmd reads batch files while running them.
   The step then:
   * refuses while another voice-midi session is running (`session.lock`), and retries next launch
   * backs up the current files to `…/voice-midi/updates/backups/` (the last 2 are kept)
   * swaps in the new files. **`.venv`, `.git` and everything in your per-user dir (config.yaml, state.json,
     your own controllers/) are never touched.**
   * runs `pip install -r requirements.txt` only if `requirements.txt` changed
   * runs a self-test (imports the app, parses "tempo one twenty eight" and "load 808 kick on pad 3", loads the config)
   * **rolls back automatically** if pip or the self-test fails, and remembers that version as bad so it isn't re-downloaded.
   * on Windows, a locked file (e.g. antivirus scanning, or a file open in Explorer) restores the old files and keeps the
     update pending for the next launch.
4. A folder that is a **git checkout** (has `.git`) never self-updates. Use `git pull`, or `--update --force`.

**Settings** (`updates:` in config.yaml):
```yaml
updates:
  mode: ask                 # auto | ask | off
  check_interval_hours: 24
  profiles: false           # opt-in controller-profile refresh (below)
  profiles_ref: main
```
**Turn updates off:** set `mode: off`, or set the env var `VOICE_MIDI_NO_UPDATE=1`, or start with `--no-update-check`.

**Manual:**
```
python -m voice_midi --version
python -m voice_midi --check-update      # just tell me
python -m voice_midi --update            # download, verify and install now (backup + self-test + rollback)
```
**Undo an update by hand:** copy the folder from `…/voice-midi/updates/backups/<old-version>-<time>/` back over the app folder.

### Controller-profile refresh (opt-in)
With `updates.profiles: true`, voice-midi also reads `config/controllers/SHA256SUMS` from the repo (branch/tag `profiles_ref`)
and downloads any new or changed `*.yaml` profile into your per-user `controllers/` folder. Each file must match its checksum
**and** parse as a valid profile, or it's ignored. New controllers arrive without a full release, so just add the id to
`controllers:`. Run it any time with `python -m voice_midi --refresh-profiles`.
(The checksum list comes from the same repo, so it protects against corrupted or partial downloads, not against someone who
controls the repo.)

## Publishing a new version (maintainer)

1. Change the code. If you touched `config/controllers/*.yaml`, regenerate the checksums:
   `python -c "from voice_midi.updater import write_profile_sums; write_profile_sums('config/controllers')"`
2. Bump **`__version__` in `voice_midi/__init__.py`**. That is the only place the version lives (pyproject reads it).
3. `python -m pytest -q`, then commit and push to `main` (CI runs the tests on Ubuntu, Windows and macOS).
4. Tag and push the tag:
   ```
   git tag v0.3.1
   git push origin v0.3.1
   ```
   `.github/workflows/release.yml` runs the tests on all 3 OSes, checks that the tag matches `__version__`,
   builds `voice-midi-0.3.1.zip` and `SHA256SUMS` with `tools/build_release.py`, and publishes the GitHub Release.
   Installed copies pick it up on their next check.
5. To pull a bad release, delete or mark it as a pre-release on GitHub (the updater ignores drafts and pre-releases), then ship a higher version.

Build locally to inspect: `python tools/build_release.py` → `dist/`.

## Commands (all accept number words: "pad three", "one twenty eight", "eight oh eight")

| Say | Does |
|---|---|
| load / put / place **SOUND** on [controller N] pad N | assign + light pad, load in Live |
| put **SOUND** on pad N on **launchpad / left / right** | controllers by name or alias |
| load **SOUND** into track N slot N | audio clip in Live clip slot (Live 12+) |
| hit / trigger pad N [on controller N] | play the pad |
| clear pad N, list pads | manage assignments (saved in the per-user dir, see below) |
| arm / disarm / mute / unmute / solo / select track N | track control |
| play scene N, play clip N on track N, stop track N | session view |
| play, stop, record, undo | transport |
| tempo N, bpm N, N bpm | tempo |
| next preset / previous preset | CC for mapping |
| play deck N, stop deck N, cue N on deck N | AUTO/PILOT |
| switch to ableton / logic / autopilot | change target (logic: Mac only) |

Sound names come from `sounds:` in `config/config.yaml`; close matches ("snair") still work.

## Adding a controller profile

1. `cp config/controllers/_TEMPLATE.yaml config/controllers/my_pad.yaml`
2. Set `id`, `name`, `port_match` (part of the name shown by `--list-ports`), and the pad notes —
   either `layout: list` with notes in pad order (pad 1 first) or `layout: grid` with `base_note`, `rows`, `cols`, `row_stride`.
   Tip: run `mido-ports` or the MIDI Monitor app and press each pad to read its note.
3. Fill in `led.colors` (velocity values) or set `led.supported: false`.
4. Add the `id` to `controllers:` in `config.yaml`, run `pytest -q` (checks the profile loads, has no duplicate notes).

## Files

```
voice_midi/      numbers.py (spoken numbers)  parser.py (grammar)  config.py (YAML/profiles/aliases)
                 engine.py (pads, LEDs, routing)  outputs/targets.py (Ableton/Logic/AUTO-PILOT)
                 outputs/transport.py (MIDI/OSC + dry-run)  speech.py (text/Vosk/whisper)  cli.py
                 platform_info.py (OS detection, per-OS ports/paths)  outputs/keys.py (shortcuts: osascript / pynput)
config/          config.yaml, controllers/*.yaml
run.bat, run.ps1 Windows launchers;  run.sh  macOS/Linux launcher
extras/          voicemidi_handler.py (AbletonOSC add-on for loading by name)
                 updater.py (self-update, profile refresh)
tools/           build_release.py (release zip + SHA256SUMS)
.github/         workflows/ci.yml (tests on PRs/pushes), workflows/release.yml (tag v* -> GitHub Release)
tests/           parser, mapping, simulated-Windows and updater tests
```

## Upgrade roadmap

1. **Hardware pass**: verify every profile's port names, pad order and LED palette; flip `verified: true`.
2. **Test the AbletonOSC add-on in Live 12**, add OSC replies so the app confirms "loaded" vs "not found".
3. **Hands-free mode**: wake word / VAD instead of Enter push-to-talk; a foot-switch or controller button as PTT.
4. **Spoken feedback** via macOS `say`, and a small menu-bar UI (rumps) showing both controllers' pad grids.
5. **Browser search by voice** ("find warm pads") listing results on the pad grid to pick by pressing.
6. **Logic**: ship a ready-made Controller Assignments preset; explore Logic's Scripter and MCU emulation for deeper control.
7. **AUTO/PILOT**: confirm the exact build/interface you use, then add sampler-slot and clip addresses + feedback on 9096.
8. Package as a signed macOS app and a Windows installer (Briefcase / PyInstaller), and bundle a loopMIDI check.
9. Windows: optionally use the Windows MIDI Services multi-client ports (when stable) to remove the exclusive-port workaround.
