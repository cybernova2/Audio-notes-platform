"""The background worker.

Every 10 seconds it takes ONE unfinished job from Postgres and moves it ONE
step forward. What the next step is depends only on what is saved in the row,
so if the worker is restarted it simply carries on where it stopped.

    QUEUED        -> create the job at Gnani             -> TRANSCRIBING
    TRANSCRIBING  -> start it, then poll Gnani's status
                  -> fetch the transcript                -> SUMMARIZING
    SUMMARIZING   -> ask the LLM for a summary           -> COMPLETED
    anything that cannot be recovered                    -> FAILED (with a readable error)

Run it on its own with:  python worker.py
(In production it runs as a thread inside the API process, see main.py.)
"""

import logging
import time
from datetime import datetime, timedelta, timezone

import db
import gnani
import llm
import storage

log = logging.getLogger("worker")

TICK_SECONDS = 10  # Gnani asks for at least 10 seconds between calls
JOB_TIMEOUT = timedelta(minutes=60)
SIGNED_URL_SECONDS = 6 * 60 * 60  # how long Gnani has to download the audio

GNANI_FINISHED = {"COMPLETED", "PARTIAL_FAILURE", "FAILED"}  # results (or errors) are in /files
GNANI_NEVER_RAN = {"START_FAILED", "CANCELLED"}

# When the loop last finished a tick (time.time()). /health reports it, so we can
# see from outside that the worker thread is alive. None until the first tick.
last_tick_at = None


def failed(message):
    return {"status": "FAILED", "error": message}


def timed_out(job):
    return datetime.now(timezone.utc) - job["queued_at"] > JOB_TIMEOUT


def next_step(job):
    """Do the next step for this job and return the columns to change."""
    if job["status"] == "SUMMARIZING":
        try:
            return {"status": "COMPLETED", "summary": llm.summarize(job["transcript"])}
        except llm.LLMError as e:
            # The transcript is already saved, so the job still counts as completed.
            return {"status": "COMPLETED", "error": f"The summary could not be generated: {e}."}

    gnani_job_id = job["gnani_job_id"]

    if gnani_job_id is None:
        audio_url = storage.signed_url(job["storage_path"], SIGNED_URL_SECONDS)
        return {
            "status": "TRANSCRIBING",
            "gnani_job_id": gnani.create_job(audio_url, job["language"]),
            "gnani_status": "CREATED",
        }

    if job["gnani_status"] == "CREATED":
        gnani.start_job(gnani_job_id)
        return {"gnani_status": "STARTING"}

    if job["gnani_status"] in GNANI_FINISHED:
        result = gnani.get_file(gnani_job_id)
        if not result.get("transcript_url"):
            reason = result.get("error_message") or "no reason given"
            return failed(f"Gnani could not transcribe this file: {reason}")
        transcript = gnani.download_transcript(result["transcript_url"])
        if not transcript.strip():
            return failed("No speech was found in this audio.")
        return {"status": "SUMMARIZING", "transcript": transcript}

    # Gnani is still working on it (STARTING / QUEUED / IN_PROGRESS): ask again.
    info = gnani.get_status(gnani_job_id)
    if info["status"] in GNANI_NEVER_RAN:
        reason = info.get("cancel_reason") or info["status"]
        return failed(f"Gnani could not start transcription: {reason}")
    if info["status"] not in GNANI_FINISHED and timed_out(job):
        return failed("Transcription timed out: Gnani did not finish within 60 minutes.")
    return {"gnani_status": info["status"]}


def run_once():
    """Advance one job by one step. Returns False when there was nothing to do."""
    with db.connect() as conn:
        # FOR UPDATE locks the row until this transaction ends, and SKIP LOCKED makes
        # a second worker skip it, so two workers can never process the same job.
        # Ordering by updated_at takes the job that has waited longest for its turn.
        job = conn.execute(
            """
            SELECT * FROM jobs
            WHERE status IN ('QUEUED', 'TRANSCRIBING', 'SUMMARIZING')
            ORDER BY updated_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        ).fetchone()
        if job is None:
            return False

        try:
            changes = next_step(job)
        except gnani.RetryableError as e:
            # Rate limit / server error / network problem: leave the job as it is and try next time.
            log.warning("job %s: temporary Gnani problem, will retry: %s", job["id"], e)
            changes = failed("Timed out: Gnani kept returning errors for 60 minutes.") if timed_out(job) else {}
        except (gnani.GnaniError, storage.StorageError) as e:
            changes = failed(str(e))
        except Exception:
            # A bug or an unexpected response. Fail the job so it cannot be retried forever.
            log.exception("job %s: unexpected error", job["id"])
            changes = failed("Something unexpected went wrong while processing this file.")

        # Column names come from the code above, never from user input.
        columns = "".join(f"{name} = %s, " for name in changes)
        conn.execute(f"UPDATE jobs SET {columns}updated_at = now() WHERE id = %s", [*changes.values(), job["id"]])
        log.info("job %s: %s", job["id"], {k: v for k, v in changes.items() if k not in ("transcript", "summary")})
        return True


def run_forever():
    global last_tick_at
    log.info("worker started")
    while True:
        try:
            run_once()
        except Exception:
            # e.g. the database is unreachable. Keep the loop alive and try again.
            log.exception("worker tick failed")
        last_tick_at = time.time()
        time.sleep(TICK_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    run_forever()
