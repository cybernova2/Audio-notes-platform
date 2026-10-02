# Architecture

How Audio Notes turns an uploaded recording into a transcript and a summary.
The same explanation is served inside the app at `/architecture`.

## Diagram

```
 Browser (Next.js on Vercel)
    |  1. POST /jobs  (audio file + language)          ^
    |                                                  |  6. GET /jobs/{id} every 5 s
    v                                                  |
 FastAPI (Render) ---- 2. stream file ---->  Storage bucket (Supabase Storage, private)
    |                                                  |
    |  3. INSERT row, status = QUEUED                  |  signed URL, valid 6 h
    v                                                  v
 PostgreSQL (Supabase)  <--- 4. worker --->  Gnani Batch STT  (create, start, poll, fetch)
    table: jobs              |
                             +---- 5. --->   Gemini  (transcript in, summary out)
```

## Components

| Component | Where | Job |
|---|---|---|
| Frontend | Next.js on Vercel | Upload form, list of past uploads, one page per upload, `/architecture` |
| Backend API | FastAPI on Render | Validates and stores uploads, serves job state as JSON |
| Database | PostgreSQL on Supabase | One table, `jobs`: the state of every upload, and the queue |
| Storage bucket | Supabase Storage (private) | Holds the audio files |
| Worker | Thread inside the API process (or `python worker.py`) | Moves each unfinished job one step forward every 10 seconds |
| Gnani | Batch Speech-to-Text API | Audio to transcript |
| Gemini | `generateContent` REST API | Transcript to summary |

## Job states

```
QUEUED ──> TRANSCRIBING ──> SUMMARIZING ──> COMPLETED
   \            |                               (summary may be missing, with an error, if the LLM failed)
    └───────────┴──> FAILED   (with a readable error; can be retried)
```

While a job is `TRANSCRIBING`, the row also stores `gnani_status`, the status Gnani last reported
(`CREATED`, `STARTING`, `QUEUED`, `IN_PROGRESS`, `COMPLETED`, `FAILED`, ...).

## Upload to transcript, step by step

1. The browser checks file type and size, then sends the file to `POST /jobs` (multipart form).
2. FastAPI validates again, streams the file into the bucket as `<job id>.<extension>`, and inserts a
   `jobs` row with status `QUEUED`. It returns the row. Nothing slow happens in this request.
3. The browser goes to `/jobs/<id>` and polls `GET /jobs/<id>` every 5 seconds.
4. The worker picks the row. Each tick it does exactly one of these, chosen from what the row contains:
   - no `gnani_job_id` yet: get a signed URL for the file and create a Gnani batch job with it
   - `gnani_status = CREATED`: start the Gnani job
   - Gnani still working: ask Gnani for the status and save it
   - Gnani finished: fetch the result, download the transcript, save it, set `SUMMARIZING`
5. On the next tick the worker sends the transcript to Gemini, saves the summary, sets `COMPLETED`.

## Where files live

Audio is stored once, in the private bucket. Postgres stores only the object path. Gnani reads the
audio through a signed URL that expires after 6 hours. Transcript and summary are text columns.

## Long audio

Gnani's standard endpoint accepts at most 60 seconds of audio. The Batch API accepts up to 4 hours
and takes the audio as a URL, so every file goes through the Batch API. It is asynchronous
(create, start, poll, fetch), which is why the app has a background worker and a status column.

## Synchronous vs background

- **In the HTTP request:** validation, saving the file to the bucket, inserting the row, all reads.
- **In the worker:** every call to Gnani and Gemini.

The `jobs` table is the queue. The worker claims a row with `SELECT ... FOR UPDATE SKIP LOCKED`,
so two workers cannot take the same job, and a crashed worker releases its row automatically.
Because the next step is decided only from the row, a restarted worker resumes the same Gnani job.

## Where the worker runs

Render's free tier has no background worker service, so the worker runs as a thread inside the
FastAPI process, started once at startup by `lifespan()` in `backend/main.py`. This is safe because
the worker keeps nothing in memory between ticks; everything it needs is in the `jobs` row.

| Event | What happens |
|---|---|
| Restart or redeploy | The thread stops with the process. Postgres rolls back the unfinished step and releases the row lock. The new process starts a new thread, which continues from the row |
| Server sleeps (about 15 minutes without requests) | The worker stops with it. An open job page keeps the server awake through its polling. Otherwise the job waits and continues at the next visit; Gnani keeps working on its side |
| Is it alive? | `GET /health` returns `worker` (`ok`, `starting`, `stalled`) and `worker_last_tick_seconds_ago` |

To run the worker as its own process instead: start `python worker.py` and set
`RUN_WORKER_IN_API=false` on the API. No code changes.

## Progress and failures

See the tables in the [README](../README.md#failure-handling). In short: upload progress is the real
percentage of bytes sent; processing progress is the real stage plus Gnani's own status; every
failure ends in a visible message, and failed jobs can be retried without uploading again.

## With more time

- Browser uploads directly to the bucket with a signed upload URL (removes the 50 MB / API-server limit)
- Worker as its own always-on service; Gnani webhook instead of polling
- User accounts, so each person sees only their uploads
- Automatic clean-up of old audio; automated tests around the worker
