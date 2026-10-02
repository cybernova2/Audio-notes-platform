"""Postgres access. Plain SQL through psycopg, one short-lived connection per operation."""

from pathlib import Path

import psycopg
from psycopg.rows import dict_row

import config


def connect():
    """Open a connection. Used as `with db.connect() as conn:` which commits on
    success, rolls back on an exception, and always closes the connection."""
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row, connect_timeout=10)


def init_schema():
    """Create the jobs table if it does not exist yet. Safe to run on every startup."""
    sql = (Path(__file__).parent / "schema.sql").read_text()
    with connect() as conn:
        conn.execute(sql)
