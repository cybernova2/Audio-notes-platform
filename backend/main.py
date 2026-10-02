"""The HTTP API. Run locally with:  uvicorn main:app --reload"""

import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
import db
import gnani
import storage
import worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # it logs full URLs, including signed ones
log = logging.getLogger("api")

# Columns the frontend is allowed to see (not the storage path or Gnani job id).
JOB_COLUMNS = "id, filename, size_bytes, language, status, gnani_status, error, transcript, summary, created_at, queued_at, updated_at"


@asynccontextmanager
async def lifespan(app):
    """Runs once when the server starts: make sure the table exists, start the worker."""
    db.init_schema()
    if config.RUN_WORKER_IN_API:
        threading.Thread(target=worker.run_forever, daemon=True).start()
    yield


app = FastAPI(title="Audio Notes API", lifespan=lifespan)

# The frontend is served from a different origin (localhost:3000 / Vercel),
# so the browser needs our permission to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(psycopg.Error)
def database_error(request, exc):
    """Any database failure becomes a clean 503 instead of a stack trace."""
    log.error("database error: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "The database is unavailable right now. Please try again."})


@app.get("/health")
def health():
    """Is the API up, can it reach Postgres, and is the worker loop still ticking?"""
    try:
        with db.connect() as conn:
            conn.execute("SELECT 1")
        database = "ok"
    except psycopg.Error:
        database = "unavailable"

    # A tick normally ends every ~10 s; a slow step (LLM retries) can take a couple of minutes.
    if not config.RUN_WORKER_IN_API:
        worker_state, seconds_ago = "runs as a separate process", None
    elif worker.last_tick_at is None:
        worker_state, seconds_ago = "starting", None
    else:
        seconds_ago = round(time.time() - worker.last_tick_at)
        worker_state = "ok" if seconds_ago < 300 else "stalled"

    return {"status": "ok", "database": database, "worker": worker_state, "worker_last_tick_seconds_ago": seconds_ago}


@app.get("/config")
def get_config():
    """What the upload form needs to know, so the rules live in one place."""
    return {
        "languages": gnani.LANGUAGES,
        "extensions": sorted(gnani.AUDIO_EXTENSIONS),
        "max_upload_mb": config.MAX_UPLOAD_MB,
    }


@app.post("/jobs", status_code=201)
def create_job(file: UploadFile, language: str = Form("en-IN")):
    """Receive an audio file, put it in the bucket and queue it for the worker.
    Returns immediately; transcription happens in the background."""
    extension = Path(file.filename or "").suffix.lower()
    if extension not in gnani.AUDIO_EXTENSIONS:
        allowed = ", ".join(sorted(gnani.AUDIO_EXTENSIONS))
        raise HTTPException(400, f"Unsupported file type '{extension}'. Allowed: {allowed}")
    if language not in gnani.LANGUAGES:
        raise HTTPException(400, f"Unsupported language '{language}'.")
    if not file.size:
        raise HTTPException(400, "The file is empty.")
    if file.size > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"The file is larger than the {config.MAX_UPLOAD_MB} MB limit.")

    job_id = uuid.uuid4()
    storage_path = f"{job_id}{extension}"
    try:
        storage.upload(storage_path, file.file, file.size, file.content_type or "application/octet-stream")
    except storage.StorageError as e:
        log.error("upload failed: %s", e)
        raise HTTPException(502, "Could not save the file to storage. Please try again.")

    with db.connect() as conn:
        return conn.execute(
            f"""
            INSERT INTO jobs (id, filename, storage_path, size_bytes, language)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING {JOB_COLUMNS}
            """,
            [job_id, file.filename, storage_path, file.size, language],
        ).fetchone()


@app.get("/jobs")
def list_jobs():
    """Past uploads, newest first (without the long transcript and summary text)."""
    with db.connect() as conn:
        return conn.execute(
            """
            SELECT id, filename, size_bytes, language, status, error, created_at
            FROM jobs ORDER BY created_at DESC LIMIT 100
            """
        ).fetchall()


@app.get("/jobs/{job_id}")
def get_job(job_id: uuid.UUID):
    """One upload with its current status, transcript and summary. The frontend polls this."""
    with db.connect() as conn:
        job = conn.execute(f"SELECT {JOB_COLUMNS} FROM jobs WHERE id = %s", [job_id]).fetchone()
    if job is None:
        raise HTTPException(404, "Upload not found.")
    return job


@app.post("/jobs/{job_id}/retry")
def retry_job(job_id: uuid.UUID):
    """Put a failed job back in the queue. The audio is still in the bucket, so no re-upload.
    If the transcript already exists, only the summary is redone."""
    with db.connect() as conn:
        job = conn.execute(
            f"""
            UPDATE jobs SET
                status       = CASE WHEN transcript IS NULL THEN 'QUEUED' ELSE 'SUMMARIZING' END,
                error        = NULL,
                gnani_job_id = CASE WHEN transcript IS NULL THEN NULL ELSE gnani_job_id END,
                gnani_status = CASE WHEN transcript IS NULL THEN NULL ELSE gnani_status END,
                queued_at    = now(),
                updated_at   = now()
            WHERE id = %s AND (status = 'FAILED' OR (status = 'COMPLETED' AND summary IS NULL))
            RETURNING {JOB_COLUMNS}
            """,
            [job_id],
        ).fetchone()
    if job is None:
        raise HTTPException(409, "This upload cannot be retried.")
    return job


@app.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: uuid.UUID):
    """Delete a finished upload: the row first, then the audio file in the bucket.
    Jobs that are still being processed cannot be deleted, so the worker is never
    left holding a job that has disappeared."""
    with db.connect() as conn:
        job = conn.execute(
            "DELETE FROM jobs WHERE id = %s AND status IN ('COMPLETED', 'FAILED') RETURNING storage_path",
            [job_id],
        ).fetchone()
    if job is None:
        raise HTTPException(409, "This upload cannot be deleted: it does not exist or is still being processed.")
    try:
        storage.delete(job["storage_path"])
    except storage.StorageError as e:
        # The upload is gone for the user; the leftover file only costs storage space.
        log.error("could not delete %s from storage: %s", job["storage_path"], e)
