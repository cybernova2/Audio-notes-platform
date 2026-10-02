"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { uploadAudio } from "@/lib/api";
import { formatSize } from "@/lib/status";

// `config` comes from GET /config: allowed extensions, languages and the size limit.
export default function UploadForm({ config }) {
  const router = useRouter();
  const [file, setFile] = useState(null);
  const [language, setLanguage] = useState("en-IN");
  const [percent, setPercent] = useState(null); // null = not uploading
  const [error, setError] = useState(null);

  // Check the file in the browser first, so obvious mistakes fail instantly
  // instead of after a long upload. The backend checks the same things again.
  function validate(chosen) {
    const extension = chosen.name.includes(".") ? "." + chosen.name.split(".").pop().toLowerCase() : "";
    if (!config.extensions.includes(extension)) {
      return `"${chosen.name}" is not a supported audio file. Allowed: ${config.extensions.join(", ")}`;
    }
    if (chosen.size === 0) return "This file is empty.";
    if (chosen.size > config.max_upload_mb * 1024 * 1024) {
      return `This file is ${formatSize(chosen.size)}. The limit is ${config.max_upload_mb} MB.`;
    }
    return null;
  }

  function chooseFile(event) {
    const chosen = event.target.files[0] || null;
    setFile(chosen);
    setError(chosen ? validate(chosen) : null);
  }

  async function submit(event) {
    event.preventDefault();
    setError(null);
    setPercent(0);
    try {
      const job = await uploadAudio(file, language, setPercent);
      router.push(`/jobs/${job.id}`); // the job page shows the rest of the progress
    } catch (e) {
      setError(e.message);
      setPercent(null);
    }
  }

  const uploading = percent !== null;

  return (
    <form className="card" onSubmit={submit}>
      <h2>Upload audio</h2>

      <label className="field">
        <span>Audio file</span>
        <input type="file" accept={config.extensions.join(",")} onChange={chooseFile} disabled={uploading} />
        <small>
          {config.extensions.join(" ")} · up to {config.max_upload_mb} MB · any length up to 4 hours
        </small>
      </label>

      <label className="field">
        <span>Language spoken</span>
        <select value={language} onChange={(e) => setLanguage(e.target.value)} disabled={uploading}>
          {Object.entries(config.languages).map(([code, name]) => (
            <option key={code} value={code}>
              {name}
            </option>
          ))}
        </select>
      </label>

      {error && <p className="notice bad">{error}</p>}

      {uploading ? (
        <div>
          <div className="bar">
            <div className="bar-fill" style={{ width: `${percent}%` }} />
          </div>
          <p className="muted">
            {percent < 100 ? `Uploading ${file.name}: ${percent}%` : "Upload received. Saving it to storage…"}
          </p>
        </div>
      ) : (
        <button type="submit" disabled={!file || Boolean(error)}>
          Upload and transcribe
        </button>
      )}
    </form>
  );
}
