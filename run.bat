@echo off
rem voice-midi launcher for Windows cmd.exe
rem   run.bat --dry-run      (first run creates .venv and installs requirements)
rem   run.bat --list-ports
rem   run.bat --speech vosk
rem cmd reads .bat files line by line while running, so an update must never rewrite the
rem file being executed: we re-launch from a temp copy and work on %VM_HOME% from there.
if not defined VM_HOME (
  set "VM_HOME=%~dp0"
  copy /y "%~f0" "%TEMP%\voice-midi-launch.bat" >nul
  "%TEMP%\voice-midi-launch.bat" %*
)
setlocal
cd /d "%VM_HOME%"
if not exist ".venv\Scripts\python.exe" (
  echo Creating .venv ...
  py -3.12 -m venv .venv 2>nul || py -3 -m venv .venv || python -m venv .venv
  if errorlevel 1 ( echo Python not found. Install it: winget install Python.Python.3.12 & exit /b 1 )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
rem install an update downloaded last time (backup + self-test + auto-rollback)
".venv\Scripts\python.exe" -m voice_midi.updater --apply-pending-safe
if errorlevel 1 echo voice-midi: update step failed; starting current version
set VOICE_MIDI_UPDATE_APPLIED=1
".venv\Scripts\python.exe" -m voice_midi %*
set "RC=%errorlevel%"
endlocal & set "VM_HOME=" & exit /b %RC%
