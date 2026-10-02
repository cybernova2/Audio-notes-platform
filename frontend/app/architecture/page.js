export const metadata = { title: "Architecture · Audio Notes" };

const GITHUB_URL = "https://github.com/REPLACE_ME/audio-notes";

const DIAGRAM = `
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
`;

// A static page: no data loading, so it is rendered on the server as plain HTML.
export default function ArchitecturePage() {
  return (
    <article className="prose">
      <h1>Architecture</h1>
      <p className="lead">How this app turns an uploaded recording into a transcript and a summary.</p>
      <p>
        Source code: <a href={GITHUB_URL}>{GITHUB_URL}</a>
      </p>

      <pre className="diagram">{DIAGRAM}</pre>

      <h2>The parts</h2>
      <ul>
        <li>
          <strong>Frontend:</strong> Next.js (App Router), deployed on Vercel. Three pages: the upload form with the list
          of past uploads, one page per upload, and this page.
        </li>
        <li>
          <strong>Backend:</strong> FastAPI, deployed on Render. The endpoints that matter: <code>POST /jobs</code>,{" "}
          <code>GET /jobs</code>, <code>GET /jobs/{"{id}"}</code>, <code>POST /jobs/{"{id}"}/retry</code> and{" "}
          <code>DELETE /jobs/{"{id}"}</code>.
        </li>
        <li>
          <strong>Database:</strong> PostgreSQL on Supabase. One table, <code>jobs</code>, with one row per upload: file
          name, where the file is stored, status, Gnani&apos;s job id, transcript, summary, error.
        </li>
        <li>
          <strong>Storage bucket:</strong> Supabase Storage, private. Audio files live here, never in Postgres. The
          database only stores the object path.
        </li>
        <li>
          <strong>Background worker:</strong> a loop that runs every 10 seconds, takes one unfinished job from Postgres
          and moves it one step forward.
        </li>
        <li>
          <strong>Gnani ASR:</strong> the Batch Speech-to-Text API does the transcription.
        </li>
        <li>
          <strong>LLM:</strong> Google Gemini writes the summary from the transcript.
        </li>
      </ul>

      <h2>From upload to transcript</h2>
      <ol>
        <li>
          The browser checks the file type and size, then sends the file to <code>POST /jobs</code>. The upload bar
          shows the real percentage sent.
        </li>
        <li>
          FastAPI validates the file again, streams it into the storage bucket, and inserts a row into{" "}
          <code>jobs</code> with status <code>QUEUED</code>. It responds straight away with the new job. Nothing slow
          happens inside this request.
        </li>
        <li>The browser moves to the job page and starts polling.</li>
        <li>
          The worker finds the queued row. It asks the bucket for a signed URL (a temporary link to the private file)
          and creates a batch job at Gnani with that URL. Gnani&apos;s job id is saved in the row and the status becomes{" "}
          <code>TRANSCRIBING</code>.
        </li>
        <li>
          On the following ticks the worker starts the Gnani job, then asks Gnani for its status every 10 seconds. Each
          answer (queued, in progress, completed) is saved in the row, which is what the job page displays.
        </li>
        <li>
          When Gnani has finished, the worker downloads the transcript, saves it, and sets the status to{" "}
          <code>SUMMARIZING</code>. The transcript is visible on the page from this moment.
        </li>
        <li>
          The worker sends the transcript to Gemini, saves the summary, and sets the status to <code>COMPLETED</code>.
        </li>
      </ol>

      <h2>Where files live</h2>
      <p>
        The audio is stored once, in a private Supabase Storage bucket, named after the job id. The backend never
        writes it to its own disk permanently and never puts it in Postgres. Gnani reads it through a signed URL that
        expires after 6 hours. Transcripts and summaries are text, so they are stored in the <code>jobs</code> row.
      </p>

      <h2>How long audio is handled</h2>
      <p>
        Gnani&apos;s standard speech-to-text endpoint only accepts audio up to 60 seconds, so it cannot be used for a 2
        minute recording. I use Gnani&apos;s Batch API instead, which accepts files up to 4 hours. It is asynchronous:
        you create a job, start it, and poll until it finishes. Every file takes this one path, short or long, so there
        is only one code path to maintain and test.
      </p>
      <p>
        The Batch API can take the audio as a URL with no size limit, which is why the worker hands it a signed URL to
        the bucket instead of sending the bytes. The transcript of even a 4 hour recording fits in Gemini&apos;s context
        window in one request, so the summary step needs no chunking.
      </p>
      <p>
        The upload limit in this deployment is 50 MB per file, which is the per-file limit of Supabase&apos;s free tier,
        not a limit of the design.
      </p>

      <h2>Synchronous vs background</h2>
      <ul>
        <li>
          <strong>Synchronous (inside the HTTP request):</strong> validating the file, saving it to the bucket,
          inserting the row, and all the read endpoints.
        </li>
        <li>
          <strong>Background (the worker):</strong> everything that talks to Gnani or Gemini. These take from 30 seconds
          to many minutes, so no request ever waits for them.
        </li>
      </ul>
      <p>
        There is no Redis or Celery. The <code>jobs</code> table is the queue: the worker selects the unfinished row
        that has waited longest, using <code>SELECT ... FOR UPDATE SKIP LOCKED</code> so that two workers could never
        take the same job. Each tick does exactly one step, and the next step is decided only from what is saved in the
        row. If the worker crashes or the server restarts, it reads the row again and continues with the same Gnani job
        instead of starting over.
      </p>
      <p>
        In this deployment the worker runs as a thread inside the FastAPI process, because the free hosting tier has no
        separate worker service. The same code runs as its own process with <code>python worker.py</code>.
      </p>

      <h2>Progress</h2>
      <p>
        Upload progress is the real percentage of bytes sent. After that, the job page polls{" "}
        <code>GET /jobs/{"{id}"}</code> every 5 seconds and shows the actual stage (queued, transcribing, summarizing,
        completed) together with the status Gnani itself reports. Gnani does not give a meaningful percentage for a
        single file, so the page shows the stage and a running timer, not an invented percentage. Because the state is
        in the database, refreshing or closing the page loses nothing.
      </p>

      <h2>Failures</h2>
      <ul>
        <li>
          <strong>Wrong file type, empty file, too large:</strong> rejected in the browser before uploading, and again
          by the API.
        </li>
        <li>
          <strong>Upload or storage failure:</strong> the form shows the error and no job is created.
        </li>
        <li>
          <strong>Corrupted audio:</strong> Gnani rejects it. The job becomes <code>FAILED</code> and shows Gnani&apos;s
          reason.
        </li>
        <li>
          <strong>Gnani rate limit, server error or network timeout:</strong> treated as temporary. The job stays where
          it is and the worker tries again on a later tick. After 60 minutes without finishing it fails with a timeout
          message.
        </li>
        <li>
          <strong>LLM failure:</strong> retried three times. If it still fails, the transcript is kept and shown, with a
          &quot;Retry summary&quot; button.
        </li>
        <li>
          <strong>Any failed job</strong> can be retried from its page without uploading again, because the audio is
          still in the bucket.
        </li>
        <li>
          <strong>Backend unreachable:</strong> the page says so and keeps retrying.
        </li>
      </ul>

      <h2>What I would do differently with more time</h2>
      <ul>
        <li>
          Upload from the browser straight to the bucket with a signed upload URL, so large files do not pass through the
          API server, and move to a storage plan without the 50 MB limit.
        </li>
        <li>
          Run the worker as a separate service. On the free tier the server sleeps when nobody is using it, which pauses
          the worker too; jobs resume when it wakes.
        </li>
        <li>
          Use Gnani&apos;s webhook to be told when a job finishes, keeping polling as the fallback.
        </li>
        <li>
          Add user accounts. Right now there is no login, so everyone who opens the app sees the same list of uploads.
        </li>
        <li>
          Process several jobs faster. The worker makes one Gnani call every 10 seconds to stay under the rate limit, so
          each extra job in progress slows the others down.
        </li>
        <li>
          Delete audio from the bucket automatically after a retention period (today it stays until the upload is
          deleted by hand), and add automated tests around the worker.
        </li>
      </ul>
    </article>
  );
}
