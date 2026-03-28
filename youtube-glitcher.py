#!/usr/bin/env python3
"""Glitchtube – CustomTkinter desktop GUI."""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from pydub import AudioSegment

from app.audio import JobState, create_glitch, download_audio
from app.config import settings

logger = logging.getLogger(__name__)

YOUTUBE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})"
)

DEFAULT_URL = "https://www.youtube.com/watch?v=LX1ywBDk1aE"

TARGET_DURATION_MS = 30000

ACCENT = "#00ffcc"
ACCENT_HOVER = "#00cc99"
SURFACE = "#333333"
TEXT = "#e0e0e0"
TEXT_MUTED = "#666666"
ERROR = "#ff4466"
BG = "#0a0a0a"


class GlitchtubeApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Glitchtube")
        self.geometry("560x490")
        self.resizable(False, False)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        # Job state
        self.jobs: dict[str, JobState] = {}
        self.current_job_id: str | None = None
        self._source_audio: AudioSegment | None = None
        self._source_duration_s: float = 0.0
        self._output_dir: Path | None = None
        self._current_output_path: Path | None = None
        self._audio_duration: float = 0.0

        # Playback state
        self._is_playing = False
        self._is_paused = False
        self._playback_proc: subprocess.Popen | None = None
        self._playback_start: float = 0.0
        self._playback_offset: float = 0.0
        self._user_scrubbing = False

        # Reprocess state
        self._reprocess_after_id: str | None = None
        self._processing = False
        self._reprocess_error: str | None = None

        settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="GLITCHTUBE",
            font=ctk.CTkFont(family="Courier", size=34, weight="bold"),
            text_color=ACCENT,
        ).grid(row=0, column=0, pady=(30, 2))

        ctk.CTkLabel(
            self, text="Extract the essence of any YouTube video",
            font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
        ).grid(row=1, column=0, pady=(0, 25))

        # ── Input ──

        self.input_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.input_frame.grid_columnconfigure(0, weight=1)

        self.url_entry = ctk.CTkEntry(
            self.input_frame, placeholder_text="Paste YouTube URL...",
            height=42, font=ctk.CTkFont(size=13),
        )
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.url_entry.insert(0, DEFAULT_URL)
        self.url_entry.bind("<Return>", lambda _: self._start_download())

        self.submit_btn = ctk.CTkButton(
            self.input_frame, text="Glitch It", width=110, height=42,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT, text_color=BG, hover_color=ACCENT_HOVER,
            command=self._start_download,
        )
        self.submit_btn.grid(row=0, column=1)

        self.error_label = ctk.CTkLabel(
            self.input_frame, text="", text_color=ERROR,
            font=ctk.CTkFont(size=12), wraplength=400,
        )
        self.error_label.grid(row=1, column=0, columnspan=2, pady=(10, 0))

        # ── Downloading ──

        self.download_frame = ctk.CTkFrame(self, fg_color="transparent")

        self.dl_progress = ctk.CTkProgressBar(
            self.download_frame, width=420, height=10, progress_color=ACCENT,
        )
        self.dl_progress.pack(pady=(0, 12))
        self.dl_progress.set(0)

        self.dl_status = ctk.CTkLabel(
            self.download_frame, text="Starting...",
            font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
        )
        self.dl_status.pack()

        # ── Editor ──

        self.editor_frame = ctk.CTkFrame(self, fg_color="transparent")

        # Snippet slider
        snip_row = ctk.CTkFrame(self.editor_frame, fg_color="transparent")
        snip_row.pack(fill="x", pady=(0, 6))
        snip_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            snip_row, text="Snippet", font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).grid(row=0, column=0, padx=(0, 8))

        self.snip_val = ctk.CTkLabel(
            snip_row, text="600ms", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=ACCENT, width=60,
        )
        self.snip_val.grid(row=0, column=2, padx=(8, 0))

        self.snip_slider = ctk.CTkSlider(
            snip_row, from_=30, to=3000, number_of_steps=99, height=16,
            progress_color=ACCENT, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            command=self._on_param_change,
        )
        self.snip_slider.grid(row=0, column=1, sticky="ew")
        self.snip_slider.set(600)

        # Shuffle switch + info label row
        opt_row = ctk.CTkFrame(self.editor_frame, fg_color="transparent")
        opt_row.pack(fill="x", pady=(2, 8))

        self.shuffle_var = ctk.BooleanVar(value=True)
        self.shuffle_switch = ctk.CTkSwitch(
            opt_row, text="Shuffle", font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED, variable=self.shuffle_var,
            progress_color=ACCENT, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            command=self._on_param_change,
        )
        self.shuffle_switch.pack(side="left")

        self.info_label = ctk.CTkLabel(
            opt_row, text="", font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
        )
        self.info_label.pack(side="right")

        # Play / Stop
        controls = ctk.CTkFrame(self.editor_frame, fg_color="transparent")
        controls.pack(pady=(0, 8))

        self.play_btn = ctk.CTkButton(
            controls, text="\u25B6  Play", width=130, height=42,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT, text_color=BG, hover_color=ACCENT_HOVER,
            command=self._toggle_playback,
        )
        self.play_btn.pack(side="left", padx=5)

        self.stop_btn = ctk.CTkButton(
            controls, text="\u25A0  Stop", width=130, height=42,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=SURFACE, text_color=TEXT, hover_color="#444444",
            command=self._stop_playback,
        )
        self.stop_btn.pack(side="left", padx=5)

        # Scrub bar
        scrub_row = ctk.CTkFrame(self.editor_frame, fg_color="transparent")
        scrub_row.pack(fill="x", pady=(0, 10))

        self.time_cur = ctk.CTkLabel(
            scrub_row, text="0:00", font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED, width=40,
        )
        self.time_cur.pack(side="left")

        self.scrub_slider = ctk.CTkSlider(
            scrub_row, from_=0, to=1, number_of_steps=1000, height=16,
            progress_color=ACCENT, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            command=self._on_scrub_drag,
        )
        self.scrub_slider.pack(side="left", fill="x", expand=True, padx=8)
        self.scrub_slider.set(0)
        self.scrub_slider.bind("<ButtonPress-1>", self._on_scrub_press)
        self.scrub_slider.bind("<ButtonRelease-1>", self._on_scrub_release)

        self.time_tot = ctk.CTkLabel(
            scrub_row, text="0:00", font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED, width=40,
        )
        self.time_tot.pack(side="right")

        # Save / Reset
        actions = ctk.CTkFrame(self.editor_frame, fg_color="transparent")
        actions.pack()

        self.save_btn = ctk.CTkButton(
            actions, text="Save MP3", width=130, height=42,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT, text_color=BG, hover_color=ACCENT_HOVER,
            command=self._save_file,
        )
        self.save_btn.pack(side="left", padx=5)

        self.reset_btn = ctk.CTkButton(
            actions, text="Make Another", width=130, height=42,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=SURFACE, text_color=TEXT, hover_color="#444444",
            command=self._reset,
        )
        self.reset_btn.pack(side="left", padx=5)

        self._show_state("input")

    def _show_state(self, state: str):
        for f in (self.input_frame, self.download_frame, self.editor_frame):
            f.grid_forget()
        {"input": self.input_frame, "downloading": self.download_frame,
         "editor": self.editor_frame}[state].grid(
            row=2, column=0, padx=40, sticky="ew",
        )

    @staticmethod
    def _fmt(seconds: float) -> str:
        m, s = divmod(max(int(seconds), 0), 60)
        return f"{m}:{s:02d}"

    # ── Download ──────────────────────────────────────────────────────────

    def _start_download(self):
        url = self.url_entry.get().strip()
        if not url:
            return
        if not YOUTUBE_RE.search(url):
            self.error_label.configure(text="Invalid YouTube URL.")
            return

        self.error_label.configure(text="")
        self.submit_btn.configure(state="disabled")

        job_id = uuid.uuid4().hex[:12]
        self.jobs[job_id] = JobState()
        self.current_job_id = job_id
        self._output_dir = settings.TEMP_DIR / job_id
        self._output_dir.mkdir(parents=True, exist_ok=True)

        self._show_state("downloading")
        self.dl_progress.set(0)
        self.dl_status.configure(text="Starting download...")

        threading.Thread(
            target=self._dl_thread, args=(url, job_id), daemon=True,
        ).start()
        self._poll_download()

    def _dl_thread(self, url: str, job_id: str):
        job = self.jobs[job_id]
        try:
            job.status = "downloading"
            job.message = "Starting download..."
            source_path = download_audio(url, self._output_dir, job)

            job.message = "Loading audio..."
            job.progress = 95
            self._source_audio = AudioSegment.from_mp3(source_path)

            job.status = "done"
            job.progress = 100
            job.message = "Ready!"
        except Exception as e:
            logger.exception("Download failed for job %s", job_id)
            job.status = "error"
            job.error = str(e)

    def _poll_download(self):
        job = self.jobs.get(self.current_job_id)
        if not job:
            return

        self.dl_progress.set(job.progress / 100)
        self.dl_status.configure(text=job.message or "Working...")

        if job.status == "done":
            self.submit_btn.configure(state="normal")
            self._source_duration_s = len(self._source_audio) / 1000
            self._enter_editor()
            return

        if job.status == "error":
            self.error_label.configure(text=job.error or "Download failed.")
            self.submit_btn.configure(state="normal")
            self._show_state("input")
            return

        self.after(300, self._poll_download)

    # ── Editor / parameters ───────────────────────────────────────────────

    def _enter_editor(self):
        self._show_state("editor")
        self._on_param_change()  # update labels + trigger initial processing

    def _calc_segments(self, snip_ms: int) -> int:
        return max(1, TARGET_DURATION_MS // snip_ms)

    def _on_param_change(self, _value=None):
        snip_ms = int(round(self.snip_slider.get() / 30) * 30)
        self.snip_val.configure(text=f"{snip_ms}ms")

        num = self._calc_segments(snip_ms)
        total = num * snip_ms / 1000
        self.info_label.configure(
            text=f"{num} segments \u00b7 {self._fmt(total)}",
            text_color=TEXT_MUTED,
        )

        # Debounced reprocess
        if self._reprocess_after_id:
            self.after_cancel(self._reprocess_after_id)
        self._reprocess_after_id = self.after(400, self._reprocess)

    def _reprocess(self):
        self._reprocess_after_id = None
        if self._processing or not self._source_audio:
            return

        snip_ms = int(round(self.snip_slider.get() / 30) * 30)
        num = self._calc_segments(snip_ms)
        shuf = self.shuffle_var.get()

        self._resume_after_reprocess = self._is_playing
        self._resume_offset = self._current_pos() if self._is_playing else 0.0
        self._stop_playback()
        self.info_label.configure(text="Processing...", text_color=TEXT_MUTED)
        self.play_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")
        self._processing = True

        threading.Thread(
            target=self._reprocess_thread, args=(num, snip_ms, shuf), daemon=True,
        ).start()
        self._poll_reprocess()

    def _reprocess_thread(self, num: int, snip_ms: int, shuf: bool):
        try:
            result = create_glitch(
                self._source_audio, num, snip_ms,
                shuffle=shuf, target_ms=TARGET_DURATION_MS,
            )
            out = self._output_dir / "glitch.mp3"
            result.export(str(out), format="mp3", bitrate="320k")
            self._current_output_path = out
            self._audio_duration = len(result) / 1000
            self._reprocess_error = None
        except Exception as e:
            self._reprocess_error = str(e)
        finally:
            self._processing = False

    def _poll_reprocess(self):
        if self._processing:
            self.after(100, self._poll_reprocess)
            return

        if self._reprocess_error:
            self.info_label.configure(
                text=f"Error: {self._reprocess_error}", text_color=ERROR,
            )
            return

        snip_ms = int(round(self.snip_slider.get() / 30) * 30)
        num = self._calc_segments(snip_ms)
        total = num * snip_ms / 1000
        self.info_label.configure(
            text=f"{num} segments \u00b7 {self._fmt(total)}",
            text_color=TEXT_MUTED,
        )
        self.play_btn.configure(state="normal")
        self.save_btn.configure(state="normal")
        self.time_tot.configure(text=self._fmt(self._audio_duration))
        self.scrub_slider.set(0)
        self.time_cur.configure(text="0:00")

        if self._resume_after_reprocess:
            offset = min(self._resume_offset, self._audio_duration)
            self._play_from(offset)

    # ── Playback ──────────────────────────────────────────────────────────

    def _current_pos(self) -> float:
        if self._is_playing:
            return self._playback_offset + (time.monotonic() - self._playback_start)
        return self._playback_offset

    def _start_ffplay(self, path: Path, offset: float = 0.0):
        cmd = ["ffplay", "-nodisp", "-autoexit"]
        if offset > 0:
            cmd += ["-ss", str(offset)]
        cmd.append(str(path))
        self._playback_proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._playback_start = time.monotonic()

    def _kill_proc(self):
        if self._playback_proc:
            self._playback_proc.terminate()
            try:
                self._playback_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._playback_proc.kill()
            self._playback_proc = None

    def _play_from(self, offset: float):
        path = self._current_output_path
        if not path or not path.exists():
            return
        self._kill_proc()
        self._playback_offset = offset
        try:
            self._start_ffplay(path, offset)
        except FileNotFoundError:
            return
        self._is_playing = True
        self._is_paused = False
        self.play_btn.configure(text="\u23F8  Pause")
        self._update_playback()

    def _toggle_playback(self):
        if self._is_paused:
            self._play_from(self._playback_offset)
            return
        if self._is_playing:
            self._playback_offset = self._current_pos()
            self._kill_proc()
            self._is_playing = False
            self._is_paused = True
            self.play_btn.configure(text="\u25B6  Play")
            return
        self._play_from(0.0)

    def _stop_playback(self):
        self._kill_proc()
        self._is_playing = False
        self._is_paused = False
        self._playback_offset = 0.0
        self.play_btn.configure(text="\u25B6  Play")
        self.scrub_slider.set(0)
        self.time_cur.configure(text="0:00")

    def _update_playback(self):
        if not self._is_playing:
            return
        if self._playback_proc and self._playback_proc.poll() is not None:
            self._is_playing = False
            self._is_paused = False
            self._playback_proc = None
            self._playback_offset = 0.0
            self.play_btn.configure(text="\u25B6  Play")
            self.scrub_slider.set(0)
            self.time_cur.configure(text="0:00")
            return
        if not self._user_scrubbing and self._audio_duration > 0:
            pos = self._current_pos()
            self.scrub_slider.set(min(pos / self._audio_duration, 1.0))
            self.time_cur.configure(text=self._fmt(pos))
        self.after(200, self._update_playback)

    # ── Scrub ─────────────────────────────────────────────────────────────

    def _on_scrub_press(self, _e):
        self._user_scrubbing = True

    def _on_scrub_drag(self, value: float):
        if self._audio_duration > 0:
            self.time_cur.configure(text=self._fmt(value * self._audio_duration))

    def _on_scrub_release(self, _e):
        self._user_scrubbing = False
        if self._audio_duration <= 0:
            return
        target = self.scrub_slider.get() * self._audio_duration
        if self._is_playing:
            self._play_from(target)
        else:
            self._playback_offset = target
            self._is_paused = True
            self.time_cur.configure(text=self._fmt(target))

    # ── File ──────────────────────────────────────────────────────────────

    def _save_file(self):
        path = self._current_output_path
        if not path or not path.exists():
            return
        dest = filedialog.asksaveasfilename(
            defaultextension=".mp3",
            filetypes=[("MP3 Files", "*.mp3")],
            initialfile=f"glitchtube-{self.current_job_id}.mp3",
        )
        if dest:
            shutil.copy2(path, dest)

    def _reset(self):
        self._stop_playback()
        # Cancel pending reprocess before clearing state
        if self._reprocess_after_id:
            self.after_cancel(self._reprocess_after_id)
            self._reprocess_after_id = None
        self._processing = False
        self._source_audio = None
        self._source_duration_s = 0.0
        self._current_output_path = None
        self._audio_duration = 0.0
        self.current_job_id = None
        self._output_dir = None
        # Show input first so frame is visible immediately
        self._show_state("input")
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, DEFAULT_URL)
        # Reset sliders without triggering reprocess
        self.snip_slider.configure(command=None)
        self.snip_slider.set(600)
        self.snip_slider.configure(command=self._on_param_change)
        self.snip_val.configure(text="600ms")
        self.shuffle_var.set(True)

    def _on_close(self):
        self._stop_playback()
        self.destroy()


if __name__ == "__main__":
    app = GlitchtubeApp()
    app.mainloop()
