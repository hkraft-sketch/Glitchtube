const urlInput = document.getElementById("url-input");
const submitBtn = document.getElementById("submit-btn");
const errorMsg = document.getElementById("error-msg");
const inputSection = document.getElementById("input-section");
const progressSection = document.getElementById("progress-section");
const progressFill = document.getElementById("progress-fill");
const statusMsg = document.getElementById("status-msg");
const resultSection = document.getElementById("result-section");
const audioPlayer = document.getElementById("audio-player");
const downloadBtn = document.getElementById("download-btn");
const resetBtn = document.getElementById("reset-btn");

function showSection(name) {
  inputSection.hidden = name !== "input";
  progressSection.hidden = name !== "progress";
  resultSection.hidden = name !== "result";
}

function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.hidden = false;
  submitBtn.disabled = false;
  showSection("input");
}

submitBtn.addEventListener("click", async () => {
  const url = urlInput.value.trim();
  if (!url) return;

  errorMsg.hidden = true;
  submitBtn.disabled = true;

  try {
    const res = await fetch("/api/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });

    if (!res.ok) {
      const err = await res.json();
      showError(err.detail || "Something went wrong.");
      return;
    }

    const { job_id } = await res.json();
    showSection("progress");
    progressFill.style.width = "0%";
    statusMsg.textContent = "Starting...";

    const evtSource = new EventSource(`/api/progress/${job_id}`);

    evtSource.onmessage = (e) => {
      const data = JSON.parse(e.data);
      progressFill.style.width = `${data.progress}%`;
      statusMsg.textContent = data.message;

      if (data.status === "done") {
        evtSource.close();
        audioPlayer.src = `/api/stream/${job_id}`;
        downloadBtn.href = `/api/download/${job_id}`;
        showSection("result");
        submitBtn.disabled = false;
      }

      if (data.status === "error") {
        evtSource.close();
        showError(data.error || "Processing failed.");
      }
    };

    evtSource.onerror = () => {
      evtSource.close();
      showError("Lost connection to server.");
    };
  } catch {
    showError("Could not connect to server.");
  }
});

resetBtn.addEventListener("click", () => {
  urlInput.value = "";
  audioPlayer.src = "";
  showSection("input");
});

urlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") submitBtn.click();
});
