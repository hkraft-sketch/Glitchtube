from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from pathlib import Path

import yt_dlp
from pydub import AudioSegment

logger = logging.getLogger(__name__)


@dataclass
class JobState:
    status: str = "pending"
    progress: float = 0.0
    message: str = ""
    error: str | None = None
    created_at: float = field(default_factory=__import__("time").time)


def download_audio(url: str, output_dir: Path, job: JobState) -> Path:
    """Download YouTube audio as MP3 using yt-dlp."""
    output_template = str(output_dir / "source.%(ext)s")

    def progress_hook(d: dict) -> None:
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            if total > 0:
                job.progress = (downloaded / total) * 90
                job.message = "Downloading audio..."

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }
        ],
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [progress_hook],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        duration = info.get("duration", 0)
        if duration > 3600:
            raise ValueError("Video exceeds maximum duration of 1 hour.")
        ydl.download([url])

    source_path = output_dir / "source.mp3"
    if not source_path.exists():
        raise FileNotFoundError("Audio download failed – no output file produced.")
    return source_path


def create_glitch(
    audio: AudioSegment,
    num_parts: int,
    snippet_ms: int,
    shuffle: bool = False,
    target_ms: int = 30000,
) -> AudioSegment:
    """Split audio into parts, extract a snippet from each, optionally shuffle.

    If the snippets don't fill *target_ms*, they are looped until the target
    duration is reached.
    """
    if len(audio) < 100:
        raise ValueError("Audio is too short to process.")

    part_duration_ms = len(audio) // num_parts
    snippets: list[AudioSegment] = []

    for i in range(num_parts):
        start_ms = i * part_duration_ms
        end_ms = min(start_ms + snippet_ms, len(audio))
        if end_ms - start_ms < 5:
            continue
        snippet = audio[start_ms:end_ms].fade_in(2).fade_out(2)
        snippets.append(snippet)

    if not snippets:
        raise ValueError("Could not extract any audio snippets.")

    if shuffle:
        random.shuffle(snippets)

    # Concatenate, looping snippets until target duration is reached
    result = AudioSegment.empty()
    idx = 0
    while len(result) < target_ms and snippets:
        result += snippets[idx % len(snippets)]
        idx += 1

    return result[:target_ms]
