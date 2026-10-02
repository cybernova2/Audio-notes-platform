// Every call to the FastAPI backend goes through this file.

// NEXT_PUBLIC_ variables are baked into the browser bundle at build time.
// This is only a URL, never a secret: all API keys stay on the backend.
export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// FastAPI sends errors as {"detail": "..."}; validation errors send a list instead.
function errorMessage(data, status) {
  if (data && typeof data.detail === "string") return data.detail;
  return `The server returned an error (HTTP ${status}).`;
}

async function request(path, options) {
  let response;
  try {
    response = await fetch(API_URL + path, options);
  } catch {
    throw new Error("Cannot reach the server. Check your connection; it will keep retrying.");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(errorMessage(data, response.status));
    error.status = response.status;
    throw error;
  }
  return data;
}

export const getConfig = () => request("/config");
export const listJobs = () => request("/jobs");
export const getJob = (id) => request(`/jobs/${id}`);
export const retryJob = (id) => request(`/jobs/${id}/retry`, { method: "POST" });
export const deleteJob = (id) => request(`/jobs/${id}`, { method: "DELETE" });

// Uploads use XMLHttpRequest instead of fetch because only XHR reports
// upload progress, which is what lets us show a real percentage.
export function uploadAudio(file, language, onProgress) {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    form.append("language", language);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}/jobs`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      let data = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {}
      if (xhr.status >= 200 && xhr.status < 300 && data) resolve(data);
      else reject(new Error(errorMessage(data, xhr.status)));
    };
    xhr.onerror = () => reject(new Error("Upload failed: the connection to the server was lost. Please try again."));
    xhr.send(form);
  });
}
