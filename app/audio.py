from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yt_dlp
from pydub import AudioSegment

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class JobState:
    status: str = "pending"
    progress: float = 0.0
    message: str = ""
    output_path: Path | None = None
    error: str | None = None
    created_at: float = field(default_factory=__import__("time").time)


def _download_audio(url: str, output_dir: Path, job: JobState) -> Path:
    """Download YouTube audio as MP3 using yt-dlp."""
    output_template = str(output_dir / "source.%(ext)s")

    def progress_hook(d: dict) -> None:
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            if total > 0:
                job.progress = (downloaded / total) * 40
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


def _create_glitch_audio(
    source_path: Path, job: JobState, settings: Settings
) -> AudioSegment:
    """Split audio into parts and extract first N seconds of each."""
    job.status = "processing"
    job.message = "Processing audio..."
    job.progress = 45

    audio = AudioSegment.from_mp3(source_path)

    if len(audio) < 1000:
        raise ValueError("Audio is too short to process (< 1 second).")

    part_duration_ms = len(audio) // settings.NUM_PARTS
    snippets: list[AudioSegment] = []

    for i in range(settings.NUM_PARTS):
        start_ms = i * part_duration_ms
        end_ms = min(start_ms + settings.SNIPPET_DURATION_MS, len(audio))

        if end_ms - start_ms < 100:
            continue

        snippets.append(audio[start_ms:end_ms])
        job.progress = 45 + ((i + 1) / settings.NUM_PARTS) * 45
        job.message = f"Extracting snippet {i + 1}/{settings.NUM_PARTS}..."

    if not snippets:
        raise ValueError("Could not extract any audio snippets.")

    result = snippets[0]
    for snippet in snippets[1:]:
        result += snippet

    return result


def process_audio(
    job_id: str, url: str, jobs: dict[str, JobState], settings: Settings
) -> None:
    """Full pipeline: download → split → concat → export."""
    job = jobs[job_id]
    output_dir = settings.TEMP_DIR / job_id

    try:
        output_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Download
        job.status = "downloading"
        job.message = "Starting download..."
        source_path = _download_audio(url, output_dir, job)

        # Step 2: Process
        result = _create_glitch_audio(source_path, job, settings)

        # Step 3: Export
        job.message = "Exporting final audio..."
        job.progress = 95
        output_path = output_dir / f"glitch.{settings.OUTPUT_FORMAT}"
        result.export(str(output_path), format=settings.OUTPUT_FORMAT, bitrate="320k")

        job.status = "done"
        job.progress = 100
        job.message = "Done!"
        job.output_path = output_path

    except Exception as e:
        logger.exception("Processing failed for job %s", job_id)
        job.status = "error"
        job.error = str(e)
        job.message = f"Error: {e}"
