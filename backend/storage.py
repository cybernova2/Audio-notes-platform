"""Supabase Storage (the bucket where audio files live), called over its REST API."""

import httpx

import config

CHUNK_SIZE = 1024 * 1024  # read and send the file 1 MB at a time


class StorageError(Exception):
    pass


def _headers():
    return {"Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}", "apikey": config.SUPABASE_SERVICE_KEY}


def _object_url(path):
    return f"{config.SUPABASE_URL}/storage/v1/object/{config.SUPABASE_BUCKET}/{path}"


def _chunks(file):
    while chunk := file.read(CHUNK_SIZE):
        yield chunk


def upload(path, file, size_bytes, content_type):
    """Stream an open binary file into the bucket at `path`."""
    headers = _headers() | {"Content-Type": content_type, "Content-Length": str(size_bytes)}
    try:
        r = httpx.post(_object_url(path), headers=headers, content=_chunks(file), timeout=300)
    except httpx.HTTPError as e:
        raise StorageError(f"could not reach storage ({type(e).__name__})") from e
    if r.status_code >= 400:
        raise StorageError(f"storage rejected the upload (HTTP {r.status_code}): {r.text[:200]}")


def delete(path):
    """Remove a file from the bucket."""
    try:
        r = httpx.delete(_object_url(path), headers=_headers(), timeout=30)
    except httpx.HTTPError as e:
        raise StorageError(f"could not reach storage ({type(e).__name__})") from e
    if r.status_code >= 400:
        raise StorageError(f"storage rejected the delete (HTTP {r.status_code}): {r.text[:200]}")


def signed_url(path, expires_seconds=3600):
    """A temporary public link to a private file, so Gnani can download it."""
    url = f"{config.SUPABASE_URL}/storage/v1/object/sign/{config.SUPABASE_BUCKET}/{path}"
    try:
        r = httpx.post(url, headers=_headers(), json={"expiresIn": expires_seconds}, timeout=30)
    except httpx.HTTPError as e:
        raise StorageError(f"could not reach storage ({type(e).__name__})") from e
    if r.status_code >= 400:
        raise StorageError(f"could not sign URL (HTTP {r.status_code}): {r.text[:200]}")
    return f"{config.SUPABASE_URL}/storage/v1{r.json()['signedURL']}"
