"""Gnani Batch Speech-to-Text client.

The normal Gnani endpoint only accepts audio up to 60 seconds, so we use the
Batch API, which accepts up to 4 hours and works like this:

    create_job  -> Gnani gives us a job id
    start_job   -> Gnani starts processing in its own background
    get_status  -> we ask again and again until the status is terminal
    get_file    -> gives a temporary URL to the transcript JSON (or an error message)
    download_transcript

Each function makes exactly one request to Gnani. The worker calls one of them
every 10 seconds, because Gnani rate-limits faster callers with HTTP 429.
Docs: https://docs.gnani.ai/api/STTBatch/Introduction
"""

import httpx

import config

BASE_URL = "https://api.vachana.ai/stt/v3/batch/jobs"
MODEL = "gnani-prisma-v2.5"

# Languages the Batch API supports (code -> name shown in the UI)
LANGUAGES = {
    "en-IN": "English",
    "hi-IN": "Hindi",
    "bn-IN": "Bengali",
    "kn-IN": "Kannada",
    "ml-IN": "Malayalam",
    "mr-IN": "Marathi",
    "ta-IN": "Tamil",
    "te-IN": "Telugu",
}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".mp4", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".webm", ".amr"}


class GnaniError(Exception):
    """Gnani refused or failed the request. Trying again will not help."""


class RetryableError(GnaniError):
    """Rate limit, server error or network problem. Trying again later may work."""


def _request(method, url, **kwargs):
    try:
        r = httpx.request(method, url, headers={"X-API-Key-ID": config.GNANI_API_KEY}, timeout=60, **kwargs)
    except httpx.HTTPError as e:  # timeouts and connection problems
        raise RetryableError(f"network problem ({type(e).__name__})") from e
    if r.status_code == 429 or r.status_code >= 500:
        raise RetryableError(f"HTTP {r.status_code}")
    return r


def _error(r):
    """Build a GnaniError from an error response. Gnani uses two shapes:
    {"detail": {"message": ...}} and {"error": ..., "message": ...}."""
    try:
        body = r.json()
        message = (body.get("detail") or body).get("message") or r.text
    except (ValueError, AttributeError):
        message = r.text
    return GnaniError(f"Gnani rejected the request (HTTP {r.status_code}): {message[:300]}")


def create_job(audio_url, language):
    """Register a job for one audio file that Gnani will download from `audio_url`."""
    body = {
        "config": {"model": MODEL, "language_code": language},
        "source": {"type": "cloud_storage", "auth": {"mode": "public"}, "paths": [audio_url]},
    }
    r = _request("POST", BASE_URL, json=body)
    if r.status_code != 201:
        raise _error(r)
    return r.json()["job_id"]


def start_job(job_id):
    r = _request("POST", f"{BASE_URL}/{job_id}/start")
    # 409 means "already started": fine, that happens if we crashed right after starting it.
    if r.status_code not in (202, 409):
        raise _error(r)


def get_status(job_id):
    """Returns Gnani's job object; we use its "status" and "cancel_reason"."""
    r = _request("GET", f"{BASE_URL}/{job_id}")
    if r.status_code != 200:
        raise _error(r)
    return r.json()


def get_file(job_id):
    """Returns the result entry for our one file: "transcript_url" on success, "error_message" on failure."""
    r = _request("GET", f"{BASE_URL}/{job_id}/files")
    if r.status_code != 200:
        raise _error(r)
    files = r.json()["data"]
    if not files:
        raise GnaniError("Gnani returned no result for this file")
    return files[0]


def download_transcript(transcript_url):
    """The transcript is a JSON file behind a pre-signed URL (no API key needed)."""
    try:
        r = httpx.get(transcript_url, timeout=60, follow_redirects=True)
    except httpx.HTTPError as e:
        raise RetryableError(f"network problem ({type(e).__name__})") from e
    if r.status_code != 200:
        raise RetryableError(f"transcript download returned HTTP {r.status_code}")
    return r.json().get("full_transcript") or ""
