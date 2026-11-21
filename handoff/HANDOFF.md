# voice-midi: HANDOFF (start here)

_Pack written 2026-11-21 (Kyle's local time, UTC-5) by Grok Bot for Kyle Burke. Built from real files, git state and bot transcripts; anything not verified is marked **unknown**. Re-check live state before acting._

**What it is:** Prototype (v0.3) voice-controlled MIDI controller bridge: say things like "load 808 kick on pad 3" or "tempo one twenty eight", and it drives Ableton Live, Logic Pro (Mac) or AUTO/PILOT over MIDI/OSC while re-routing and lighting the pads of two hardware controllers.

**Built by / owner bot:** Builder **unknown** (commit 2026-10-28).

**Kind:** Python app for macOS and Windows (public repo). **Overall state:** v0.3.0 published 2026-10-28 with a self-updater. Whether Kyle installed or used it on Tower is **unknown** (no install folder found in the Tower home listing).

## Where everything lives
- GitHub (public): https://github.com/bobzombers-hash/voice-midi , `main` at `cf3d268`.
- Bot box `/workspace/voice-midi/` (clone, clean).
- Master pack: `C:\Users\bobzo\Handoff\voice-midi\` (docs only).

## Reading order
1. `HANDOFF.md`: this file: what the project is, where everything lives, reading order
2. `STATUS.md`: what works, what is broken, what is waiting on Kyle, next steps
3. `ARCHITECTURE.md`: stack, folders, data flow
4. `RUNBOOK.md`: how to install, run, test, build and release
5. `DECISIONS.md`: dated decisions and the reasons, so you do not reopen them
6. `CHAT_SUMMARY.md`: what Kyle asked for, by date, with his words quoted
7. `SECRETS.md`: which secrets exist and where they live (names only, never values)


## First things to do as a new agent
1. Read the project's own README (copied into the master pack `reference/`).
2. Run its tests (see RUNBOOK.md) before changing anything.
3. Ask Kyle what he wants next; this project has no recorded open request.

## Kyle's standing rules (apply to every project)
- Ask Kyle **before**: git pushes, opening/merging PRs that deploy, destructive or production database changes, external posts, anything that costs money (billing, paid signups, paid builds), App Store / Play submissions.
- No paid services or new subscriptions without his explicit OK for that specific purchase. Build paid-vendor features switched off.
- Never print, paste or commit secrets. Ask for them through a secure form or vault, never in chat.
- Verify with evidence before saying something is done (test output, screenshot, log). Plan first on complex work.
- Add a one-line lesson to the project's AGENTS.md / log after every mistake or correction.
- Explain things in plain language. Kyle is a solo builder; do the work end to end and come back with a clear ask.
- An approval is specific: a past "yes" is not permission for the next push/deploy/build.
