# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Glitchtube

A desktop app (CustomTkinter) that takes a YouTube URL, downloads its audio, splits it into equal parts, extracts a short snippet from the start of each part, and concatenates the snippets into a single "glitch" MP3 — an audio summary of any YouTube video.

## Commands

```bash
# Install dependencies (requires Python 3.10+)
pip install -r requirements.txt

# Run the desktop GUI
python gui.py

# System dependency: ffmpeg must be installed (used by pydub, yt-dlp, and ffplay for playback)
```

There are no tests, linter, or formatter configured.

## Architecture

**GUI** — `gui.py` (entry point)

- CustomTkinter dark-themed window with three states: input → downloading → editor.
- Editor allows live adjustment of segment count (2–200), snippet duration (1–10s), and shuffle toggle. Parameter changes trigger debounced re-processing (400ms).
- Validation: total duration (segments × snippet) must not exceed source audio length.
- Audio playback via `ffplay` subprocess; pause/resume by killing and restarting with `-ss` offset.
- Scrub bar updates every 200ms via `after()`.

**Core** — `app/`

- `audio.py` — `JobState` dataclass, `download_audio` (yt-dlp download), `create_glitch` (split + optional shuffle + concatenate snippets). Both are pure functions called from the GUI.
- `config.py` — `pydantic-settings` `Settings` with `TEMP_DIR`. Configurable via env vars.

**Key design decisions:**
- Download and processing are separate steps: download once, re-process live with different parameters.
- Processing runs in a background thread to keep the GUI responsive.
- Job state is in-memory only. Temp files go to `/tmp/glitchtube/{job_id}/`.
