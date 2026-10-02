"""All settings come from environment variables (backend/.env locally, the host's dashboard in production)."""

import os

from dotenv import load_dotenv

load_dotenv()

GNANI_API_KEY = os.getenv("GNANI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")

DATABASE_URL = os.getenv("DATABASE_URL", "")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "audio")

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))  # Supabase free tier allows 50 MB per file

# Set to "false" when the worker runs as its own process (python worker.py)
RUN_WORKER_IN_API = os.getenv("RUN_WORKER_IN_API", "true").lower() == "true"

CORS_ORIGINS =[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
