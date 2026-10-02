"""
Step 1: prove the Gnani Batch STT flow works before building the app around it.

Usage (from the backend folder):
    python scripts/verify_gnani.py ../samples/short.wav
    python scripts/verify_gnani.py https://example.com/audio.mp3
    python scripts/verify_gnani.py ../samples/short.wav hi-IN

A local path is sent as a multipart upload (Gnani allows up to 10 MB that way).
A URL is sent as a "cloud_storage" source, which is what the real app will use
with a signed URL from our storage bucket.

Every raw response is printed so we can see the real shapes, not the documented ones.
"""

import json
import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.vachana.ai/stt/v3/batch/jobs"
POLL_SECONDS = 10  # Gnani docs: do not poll faster than every 10 seconds
MAX_WAIT_SECONDS = 600
TERMINAL = {"COMPLETED", "PARTIAL_FAILURE", "FAILED", "START_FAILED", "CANCELLED"}


def show(label, response):
    print(f"\n--- {label}: HTTP {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2, ensure_ascii=False)[:3000])
    except ValueError:
        print(response.text[:3000])


def send(client, method, url, **kwargs):
    """Make a request; if Gnani says 429 (rate limited), wait and try again."""
    for attempt in range(6):
        r = client.request(method, url, **kwargs)
        if r.status_code != 429:
            return r
        print(f"    429 rate limited, waiting {POLL_SECONDS}s (attempt {attempt + 1})")
        time.sleep(POLL_SECONDS)
    return r


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    source = sys.argv[1]
    language = sys.argv[2] if len(sys.argv) > 2 else "en-IN"

    api_key = os.getenv("GNANI_API_KEY")
    if not api_key:
        sys.exit("GNANI_API_KEY is empty. Put it in backend/.env")

    headers = {"X-API-Key-ID": api_key}
    config = {"model": "gnani-prisma-v2.5", "language_code": language}

    with httpx.Client(timeout=120) as client:
        # 1. create the job
        if source.startswith("http"):
            body = {
                "config": config,
                "source": {
                    "type": "cloud_storage",
                    "auth": {"mode": "public"},
                    "paths": [source],
                },
            }
            r = client.post(BASE_URL, headers=headers, json=body)
        else:
            with open(source, "rb") as audio:
                files = {
                    "config": (None, json.dumps(config), "application/json"),
                    "files": (os.path.basename(source), audio),
                }
                r = client.post(BASE_URL, headers=headers, files=files)
        show("create job", r)
        if r.status_code >= 400:
            sys.exit(1)
        job_id = r.json()["job_id"]

        # 2. start it
        r = send(client, "POST", f"{BASE_URL}/{job_id}/start", headers=headers)
        show("start job", r)
        if r.status_code >= 400:
            sys.exit(1)

        # 3. poll until a terminal status
        started = time.time()
        status = None
        while time.time() - started < MAX_WAIT_SECONDS:
            time.sleep(POLL_SECONDS)
            r = client.get(f"{BASE_URL}/{job_id}", headers=headers)
            status = r.json().get("status") if r.status_code == 200 else None
            percent = r.json().get("progress", {}).get("percent") if status else None
            print(f"[{int(time.time() - started):>4}s] HTTP {r.status_code} status={status} percent={percent}")
            if status in TERMINAL:
                break
        show("final job status", r)

        # 4. list the files (this is where the transcript URL and per-file errors are)
        r = send(client, "GET", f"{BASE_URL}/{job_id}/files", headers=headers)
        show("job files", r)
        if r.status_code >= 400 or not r.json().get("data"):
            sys.exit(1)
        file_info = r.json()["data"][0]
        if not file_info.get("transcript_url"):
            sys.exit("No transcript_url - the file failed, see error_message above.")

        # 5. download the transcript JSON (pre-signed URL, no API key needed)
        r = client.get(file_info["transcript_url"], follow_redirects=True)
        show("transcript JSON", r)
        print("\nFULL TRANSCRIPT:\n", r.json().get("full_transcript"))
        print(f"\nTotal time: {int(time.time() - started)}s")


if __name__ == "__main__":
    main()
