# Audio Notes

Upload an audio recording, get back a transcript (Gnani ASR) and a short summary (Gemini).
Built for the Gnani internship take-home task.

- **Live app:** _added after deployment_
- **Architecture page:** `/architecture` in the live app

## Features

- Upload audio (`.wav .mp3 .m4a .mp4 .flac .ogg .opus .aac .webm .amr`) up to 50 MB, any length up to 4 hours
- Transcription with Gnani's Batch Speech-to-Text API, in 8 Indian languages
- Summary written by Gemini from the transcript
- Real progress: upload percentage, then the actual processing stage
- Past uploads are listed and can be reopened; refreshing or closing the page loses nothing
- Failures are shown with a reason, and a failed job can be retried without uploading again
- A finished upload can be deleted, which removes its row and its audio file

## Architecture

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

1. The browser sends the file to `POST /jobs`.
2. FastAPI validates it, streams it into the storage bucket and inserts a `jobs` row with status `QUEUED`. The request ends here.
3. The worker (a loop that runs every 10 seconds) takes one unfinished job and moves it one step forward:
   create a Gnani batch job from a signed URL → start it → poll its status → download the transcript → ask Gemini for a summary.
4. The browser polls `GET /jobs/{id}` every 5 seconds and shows the current stage.

Job status values: `QUEUED → TRANSCRIBING → SUMMARIZING → COMPLETED`, or `FAILED`.

## Tech stack

| Part | Choice |
|---|---|
| Frontend | Next.js 16 (App Router, JavaScript, plain CSS) |
| Backend | FastAPI, uvicorn |
| Database | PostgreSQL (Supabase), accessed with `psycopg` and plain SQL |
| Storage bucket | Supabase Storage |
| Background jobs | A worker loop that uses the `jobs` table as its queue |
| Speech-to-text | Gnani Batch STT API (`gnani-prisma-v2.5`) |
| Summary | Google Gemini (`gemini-flash-lite-latest`) |
| Hosting | Vercel (frontend), Render (backend + worker) |

## Folder structure

```
backend/
  main.py           FastAPI app: endpoints, CORS, starts the worker
  worker.py         background worker: one job, one step, every 10 seconds
  gnani.py          Gnani Batch STT client (one function per API call)
  llm.py            Gemini summary call
  storage.py        Supabase Storage: upload + signed URL
  db.py             Postgres connection helper
  config.py         settings from environment variables
  schema.sql        the jobs table
  scripts/verify_gnani.py   standalone script used to test the Gnani API first
frontend/
  app/page.js               home: upload form + past uploads
  app/jobs/[id]/page.js     one upload: progress, transcript, summary
  app/architecture/page.js  how the system works
  components/               UploadForm, JobList
  lib/api.js                all calls to the backend
  lib/status.js             turns job status into text for the user
render.yaml         backend deployment settings for Render
```

## Local setup

Requirements: Python 3.13, Node 20+, a Supabase project (Postgres + a private Storage bucket named `audio`), a Gnani API key and a Gemini API key.

### Environment variables

Backend (`backend/.env`, copy from `backend/.env.example`):

| Variable | Meaning |
|---|---|
| `GNANI_API_KEY` | Gnani key, sent as the `X-API-Key-ID` header |
| `GEMINI_API_KEY` | Gemini key |
| `GEMINI_MODEL` | optional, default `gemini-flash-lite-latest` |
| `DATABASE_URL` | Supabase Postgres URI (use the Session pooler one) |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Supabase secret (service role) key |
| `SUPABASE_BUCKET` | bucket name, default `audio` |
| `MAX_UPLOAD_MB` | optional, default `50` |
| `RUN_WORKER_IN_API` | optional, default `true` |
| `CORS_ORIGINS` | comma-separated frontend origins, default `http://localhost:3000` |

Frontend (`frontend/.env.local`):

| Variable | Meaning |
|---|---|
| `NEXT_PUBLIC_API_URL` | backend URL, default `http://localhost:8000` |

### Database

Nothing to run by hand. On startup the API executes `backend/schema.sql`, which creates the `jobs` table if it does not exist.

### Run the backend (and worker)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The worker starts as a thread inside the API. To run it as a separate process instead, set `RUN_WORKER_IN_API=false` and run:

```bash
python worker.py
```

### Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000.

## API endpoints

| Method | Path | What it does |
|---|---|---|
| `GET` | `/health` | API is up; can it reach Postgres |
| `GET` | `/config` | allowed file types, languages, size limit (used by the upload form) |
| `POST` | `/jobs` | multipart `file` + `language`; stores the file, queues the job, returns it (201) |
| `GET` | `/jobs` | past uploads, newest first |
| `GET` | `/jobs/{id}` | one upload: status, transcript, summary, error |
| `POST` | `/jobs/{id}/retry` | re-queue a failed job, or redo only the summary if the transcript exists |
| `DELETE` | `/jobs/{id}` | delete a finished upload: its row and its audio file (409 while it is still processing) |

FastAPI also serves interactive docs at `/docs`.

## Deployment

- **Database + storage:** one Supabase project. Create a private bucket named `audio`.
- **Backend + worker:** Render web service from `render.yaml` (root directory `backend`, start command `uvicorn main:app --host 0.0.0.0 --port $PORT`). Set the backend environment variables in the Render dashboard, with `CORS_ORIGINS` set to the Vercel URL.
- **Frontend:** Vercel project with root directory `frontend` and `NEXT_PUBLIC_API_URL` set to the Render URL.

## Failure handling

| What goes wrong | What happens |
|---|---|
| Wrong file type, empty file, file too large | Rejected in the browser, and again by the API (400 / 413) |
| Upload interrupted, storage bucket error | The form shows the error; no job is created |
| Corrupted or non-audio file | Gnani rejects it; the job becomes `FAILED` with Gnani's reason |
| Gnani rate limit (429), 5xx, network timeout | Treated as temporary; the worker tries again on a later tick |
| Gnani never finishes | The job fails with a timeout message after 60 minutes |
| Gemini fails | Retried 3 times; then the job completes with the transcript and a "Retry summary" button |
| Worker or server crashes mid-job | On restart the worker continues the same Gnani job from the saved state |
| Database unreachable | API returns 503 with a readable message; the page shows it and keeps retrying |
| Backend unreachable | The page says so and keeps retrying |

API keys only exist on the backend. Error messages shown to users never contain keys or stack traces.

## Design decisions

- **Gnani Batch API for everything.** The standard endpoint only accepts 60 seconds of audio; the batch API accepts 4 hours. Using it for every file means one code path.
- **Postgres as the queue, no Redis or Celery.** The `jobs` table already holds the state. The worker claims a row with `SELECT ... FOR UPDATE SKIP LOCKED`, so a second worker could never take the same job.
- **One step per tick, decided from the row.** Gnani rate-limits calls made less than about 10 seconds apart, so the worker makes one Gnani call per tick. Since the next step depends only on what is saved, a restart resumes instead of starting over.
- **Polling, not WebSockets.** The worker itself only learns about progress every 10 seconds, so a 5 second poll from the browser loses nothing and needs no extra infrastructure.
- **Audio in the bucket, text in Postgres.** Gnani downloads the audio through a signed URL, so the bytes are never sent twice by the backend.
- **Worker inside the API process in production.** The free hosting tier has no separate worker service. `worker.py` runs unchanged as its own process.

## Known limitations and future improvements

- No login: everyone who opens the app sees the same list of uploads.
- 50 MB upload limit (Supabase free tier). Direct browser-to-bucket uploads with a signed upload URL would remove the API server from the upload path.
- On the free Render tier the server sleeps when idle, which pauses the worker; jobs resume when it wakes, and the first request after a sleep takes up to a minute.
- One Gnani call every 10 seconds in total, so several jobs in progress slow each other down.
- If the database write fails right after a Gnani job is created, a second Gnani job would be created on the next tick.
- Uses Gnani polling only; Gnani's webhook could remove most of the polling.
- No automated tests; audio stays in the bucket until the upload is deleted by hand.
