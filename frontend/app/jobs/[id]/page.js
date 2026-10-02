"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { deleteJob, getJob, retryJob } from "@/lib/api";
import { STEPS, currentStep, describe, formatDuration, formatSize, isActive, summaryFailed } from "@/lib/status";

const POLL_MS = 5000;

// One upload: live progress while it is processed, then the transcript and summary.
export default function JobPage() {
  const { id } = useParams();
  const router = useRouter();
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null); // problem talking to our API
  const [notFound, setNotFound] = useState(false);
  const [pollRound, setPollRound] = useState(0); // increased by retry() to start polling again
  const [now, setNow] = useState(() => Date.now());

  const active = job ? isActive(job) : false;

  // Polling: ask the API for this job, and ask again 5 seconds later for as
  // long as it is still being processed. Because the state lives in Postgres,
  // refreshing or reopening the page just picks up wherever the job is.
  useEffect(() => {
    let stopped = false;
    let timer;

    async function load() {
      try {
        const loaded = await getJob(id);
        if (stopped) return;
        setJob(loaded);
        setError(null);
        if (isActive(loaded)) timer = setTimeout(load, POLL_MS);
      } catch (e) {
        if (stopped) return;
        if (e.status === 404 || e.status === 422) {
          setNotFound(true);
        } else {
          setError(e.message); // e.g. network down: say so and keep trying
          timer = setTimeout(load, POLL_MS);
        }
      }
    }

    load();
    // Runs when the user leaves the page: stop polling.
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [id, pollRound]);

  // A clock that ticks every second so "running for ..." keeps moving between polls.
  useEffect(() => {
    if (!active) return;
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(tick);
  }, [active]);

  async function retry() {
    try {
      setJob(await retryJob(id));
      setError(null);
      setPollRound((n) => n + 1);
    } catch (e) {
      setError(e.message);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete "${job.filename}" and its transcript? This cannot be undone.`)) return;
    try {
      await deleteJob(id);
      router.push("/");
    } catch (e) {
      setError(e.message);
    }
  }

  if (notFound) {
    return (
      <>
        <p className="notice bad">This upload does not exist.</p>
        <Link href="/">← All uploads</Link>
      </>
    );
  }
  if (!job) {
    return <p className={error ? "notice bad" : "muted"}>{error || "Loading…"}</p>;
  }

  const step = currentStep(job);

  return (
    <>
      <Link href="/">← All uploads</Link>
      <h1 className="filename">{job.filename}</h1>
      <p className="muted">
        {formatSize(job.size_bytes)} · {job.language} · uploaded {new Date(job.created_at).toLocaleString()}
      </p>

      {error && <p className="notice bad">{error}</p>}

      {active && (
        <section className="card">
          <ol className="steps">
            {STEPS.map((name, index) => (
              <li key={name} className={index < step ? "done" : index === step ? "current" : ""}>
                {name}
              </li>
            ))}
          </ol>
          <div className="bar">
            <div className="bar-moving" />
          </div>
          <p>{describe(job)}</p>
          <p className="muted">
            Running for {formatDuration((now - new Date(job.queued_at)) / 1000)} · this page checks for updates every 5
            seconds · you can close it and come back later
          </p>
        </section>
      )}

      {job.status === "FAILED" && (
        <section className="notice bad">
          <strong>Processing failed</strong>
          <p>{job.error}</p>
          <button onClick={retry}>Try again</button>
        </section>
      )}

      {summaryFailed(job) && (
        <section className="notice warn">
          <strong>The transcript is ready, but the summary failed</strong>
          <p>{job.error}</p>
          <button onClick={retry}>Retry summary</button>
        </section>
      )}

      {job.status === "COMPLETED" && !job.error && <p className="notice good">Completed</p>}

      {job.summary && (
        <section>
          <h2>Summary</h2>
          <p className="text">{job.summary}</p>
        </section>
      )}

      {job.transcript && (
        <section>
          <h2>Transcript</h2>
          <p className="text">{job.transcript}</p>
        </section>
      )}

      {!active && (
        <p className="actions">
          <button className="danger" onClick={remove}>
            Delete this upload
          </button>
        </p>
      )}
    </>
  );
}
