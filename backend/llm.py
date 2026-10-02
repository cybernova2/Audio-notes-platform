"""Summary generation with Google Gemini, called over its REST API."""

import logging
import time

import httpx

import config

log = logging.getLogger("llm")

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
ATTEMPTS = 3

PROMPT = """You are given the transcript of an audio recording. It was produced by \
speech recognition, so it has no punctuation and may contain small mistakes.

Write a summary in the same language as the transcript, in plain text (no markdown):
1. A short paragraph (2-4 sentences) saying what the recording is about.
2. Then the heading "Key points:" followed by 3 to 6 lines, each starting with "- ".

Only use information that is in the transcript.

Transcript:
"""


class LLMError(Exception):
    pass


def summarize(transcript):
    """Returns the summary text. Retries a few times on temporary errors, then raises LLMError."""
    body = {"contents": [{"parts": [{"text": PROMPT + transcript}]}]}
    url = URL.format(model=config.GEMINI_MODEL)
    problem = "unknown error"

    for attempt in range(ATTEMPTS):
        if attempt:
            log.warning("summary attempt %d failed: %s, retrying", attempt, problem)
            time.sleep(5 * attempt)
        try:
            r = httpx.post(url, headers={"x-goog-api-key": config.GEMINI_API_KEY}, json=body, timeout=120)
        except httpx.HTTPError as e:
            problem = f"network problem ({type(e).__name__})"
            continue
        if r.status_code == 429 or r.status_code >= 500:
            problem = f"the LLM is busy or rate limited (HTTP {r.status_code})"
            continue
        if r.status_code != 200:
            raise LLMError(f"the LLM rejected the request (HTTP {r.status_code})")
        try:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError, ValueError):
            raise LLMError("the LLM returned an empty response")

    raise LLMError(problem)
