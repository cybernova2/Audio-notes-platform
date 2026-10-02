// Turns the job fields from the API into words for the user.

const ACTIVE = ["QUEUED", "TRANSCRIBING", "SUMMARIZING"];

// Still being processed, so the page should keep polling.
export function isActive(job) {
  return ACTIVE.includes(job.status);
}

// The transcript is there but the LLM failed.
export function summaryFailed(job) {
  return job.status === "COMPLETED" && Boolean(job.error);
}

// Short label + colour for the history list.
export function badge(job) {
  if (job.status === "FAILED") return { label: "Failed", tone: "bad" };
  if (summaryFailed(job)) return { label: "Completed, no summary", tone: "warn" };
  if (job.status === "COMPLETED") return { label: "Completed", tone: "good" };
  if (job.status === "QUEUED") return { label: "Queued", tone: "busy" };
  if (job.status === "TRANSCRIBING") return { label: "Transcribing", tone: "busy" };
  return { label: "Summarizing", tone: "busy" };
}

export const STEPS = ["Uploaded", "Queued", "Transcribing", "Summarizing", "Completed"];

// Index into STEPS of the step that is happening right now.
export function currentStep(job) {
  return { QUEUED: 1, TRANSCRIBING: 2, SUMMARIZING: 3, COMPLETED: 5 }[job.status];
}

// One sentence saying what is happening right now. While transcribing, this
// reflects the status Gnani itself reported the last time the worker asked.
export function describe(job) {
  if (job.status === "QUEUED") return "Waiting for the background worker to pick this up.";
  if (job.status === "SUMMARIZING") return "Transcript is ready. The LLM is writing the summary.";
  if (job.status === "TRANSCRIBING") {
    if (job.gnani_status === "QUEUED") return "Gnani has the audio. It is waiting in Gnani's queue.";
    if (job.gnani_status === "IN_PROGRESS") return "Gnani is transcribing the audio.";
    if (job.gnani_status === "COMPLETED") return "Gnani has finished. Fetching the transcript.";
    return "Sending the audio to Gnani.";
  }
  return "";
}

export function formatSize(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatDuration(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}
