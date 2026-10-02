"use client";

import { useEffect, useState } from "react";
import { getConfig, listJobs } from "@/lib/api";
import { isActive } from "@/lib/status";
import UploadForm from "@/components/UploadForm";
import JobList from "@/components/JobList";

const POLL_MS = 5000;

// Home page: the upload form and the list of past uploads.
export default function HomePage() {
  const [config, setConfig] = useState(null);
  const [jobs, setJobs] = useState(null); // null = not loaded yet
  const [error, setError] = useState(null);

  useEffect(() => {
    let stopped = false;
    let timer;

    async function load() {
      try {
        const [loadedConfig, loadedJobs] = await Promise.all([getConfig(), listJobs()]);
        if (stopped) return;
        setConfig(loadedConfig);
        setJobs(loadedJobs);
        setError(null);
        // Keep refreshing only while something is still being processed.
        if (loadedJobs.some(isActive)) timer = setTimeout(load, POLL_MS);
      } catch (e) {
        if (stopped) return;
        setError(e.message);
        timer = setTimeout(load, POLL_MS);
      }
    }

    load();
    // Runs when the user leaves the page: stop polling.
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, []);

  return (
    <>
      <h1>Audio Notes</h1>
      <p className="lead">Upload a recording and get back a transcript and a short summary.</p>

      {error && <p className="notice bad">{error}</p>}

      {config ? (
        <UploadForm config={config} />
      ) : (
        !error && <p className="notice">Connecting to the server… On the free hosting tier it can take up to a minute to wake up.</p>
      )}

      <h2>Past uploads</h2>
      {jobs ? <JobList jobs={jobs} /> : <p className="muted">Loading…</p>}
    </>
  );
}
