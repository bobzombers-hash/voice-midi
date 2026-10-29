# voice-midi launcher for Windows PowerShell.
#   .\run.ps1 --dry-run            (first run creates .venv and installs requirements)
#   .\run.ps1 --list-ports
#   .\run.ps1 --speech vosk
# If scripts are blocked:  powershell -ExecutionPolicy Bypass -File .\run.ps1 --dry-run
$ErrorActionPreference = "Continue"   # pip writes warnings to stderr; check exit codes instead
Set-Location -Path $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creating .venv with Python 3.12 (python-rtmidi has Windows wheels up to 3.12)..."
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { py -3 -m venv .venv }
    if (-not (Test-Path $py)) { Write-Error "Python not found. Install it:  winget install Python.Python.3.12"; exit 1 }
    & $py -m pip install --upgrade pip
    & $py -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Write-Error "pip install failed"; exit 1 }
}
# Install an update downloaded last time (backup + self-test + auto-rollback). PowerShell parses this
# whole script before running it, so the update may safely replace run.ps1 itself.
& $py -m voice_midi.updater --apply-pending-safe
if ($LASTEXITCODE -ne 0) { Write-Warning "voice-midi: update step failed; starting current version" }
$env:VOICE_MIDI_UPDATE_APPLIED = "1"
& $py -m voice_midi @args
exit $LASTEXITCODE
