#!/usr/bin/env bash
# voice-midi launcher for macOS/Linux:  ./run.sh --dry-run
# The whole body is one { ... } block so bash has read it all before an update replaces this file.
{
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
fi
# install an update downloaded last time (backup + self-test + auto-rollback)
.venv/bin/python -m voice_midi.updater --apply-pending-safe || echo "voice-midi: update step failed; starting current version"
export VOICE_MIDI_UPDATE_APPLIED=1
exec .venv/bin/python -m voice_midi "$@"
}
