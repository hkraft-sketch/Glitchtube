from __future__ import annotations

import asyncio
import json
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.audio import JobState, process_audio
from app.cleanup import periodic_cleanup
from app.config import settings

YOUTUBE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})"
)

jobs: dict[str, JobState] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_task = asyncio.create_task(periodic_cleanup(jobs, settings))
    yield
    cleanup_task.cancel()


app = FastAPI(title="Glitchtube", lifespan=lifespan)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Models ──────────────────────────────────────────────────────────────────


class ProcessRequest(BaseModel):
    url: str


class ProcessResponse(BaseModel):
    job_id: str


# ── Routes ──────────────────────────────────────────────────────────────────


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.post("/api/process", response_model=ProcessResponse)
async def start_processing(req: ProcessRequest):
    match = YOUTUBE_RE.search(req.url)
    if not match:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL.")

    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = JobState()

    asyncio.get_event_loop().run_in_executor(
        None, process_audio, job_id, req.url, jobs, settings
    )

    return ProcessResponse(job_id=job_id)


@app.get("/api/progress/{job_id}")
async def progress(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found.")

    async def event_stream():
        while True:
            job = jobs.get(job_id)
            if job is None:
                break

            data = json.dumps(
                {
                    "status": job.status,
                    "progress": round(job.progress, 1),
                    "message": job.message,
                    "error": job.error,
                }
            )
            yield f"data: {data}\n\n"

            if job.status in ("done", "error"):
                break

            await asyncio.sleep(0.3)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/download/{job_id}")
async def download(job_id: str):
    job = jobs.get(job_id)
    if not job or not job.output_path or not job.output_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(
        str(job.output_path),
        media_type="audio/mpeg",
        filename=f"glitchtube-{job_id}.mp3",
    )


@app.get("/api/stream/{job_id}")
async def stream(job_id: str):
    job = jobs.get(job_id)
    if not job or not job.output_path or not job.output_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(str(job.output_path), media_type="audio/mpeg")
