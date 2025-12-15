from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple, Protocol

# Optional Postgres support (psycopg v3)
try:
    import psycopg  # type: ignore
    from psycopg.rows import dict_row  # type: ignore
except Exception:  # pragma: no cover
    psycopg = None
    dict_row = None


def _is_postgres_url(url: str) -> bool:
    u = (url or "").lower()
    return u.startswith("postgres://") or u.startswith("postgresql://")


def get_db_target(track_db_path: str) -> Tuple[str, str]:
    """
    Returns ("postgres", DATABASE_URL) if DATABASE_URL is set,
    otherwise ("sqlite", track_db_path).
    """
    db_url = os.getenv("DATABASE_URL") or os.getenv("DB_URL") or ""
    if db_url and _is_postgres_url(db_url):
        return ("postgres", db_url)
    return ("sqlite", track_db_path)


# -----------------------
# SQLite implementation
# -----------------------

def _sqlite_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _sqlite_init_schema(db_path: str) -> None:
    with _sqlite_conn(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS clicks (
                token TEXT PRIMARY KEY,
                ts INTEGER NOT NULL,
                ip TEXT,
                user_agent TEXT,
                referrer TEXT,
                tg_user_id INTEGER,
                tg_username TEXT,
                tg_first_name TEXT,
                tg_last_name TEXT,
                linked_ts INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_clicks_ts ON clicks(ts DESC);
            CREATE INDEX IF NOT EXISTS idx_clicks_tg_user_id ON clicks(tg_user_id);
            """
        )


def _sqlite_insert_click(db_path: str, token: str, ts: int, ip: str, user_agent: str, referrer: str) -> None:
    with _sqlite_conn(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO clicks(token, ts, ip, user_agent, referrer)
            VALUES (?, ?, ?, ?, ?)
            """,
            (token, ts, ip, user_agent, referrer),
        )


def _sqlite_link_click_to_tg_user(
    db_path: str,
    token: str,
    tg_user_id: int,
    username: str = "",
    first_name: str = "",
    last_name: str = "",
) -> None:
    with _sqlite_conn(db_path) as conn:
        conn.execute(
            """
            UPDATE clicks
               SET tg_user_id=?,
                   tg_username=?,
                   tg_first_name=?,
                   tg_last_name=?,
                   linked_ts=strftime('%s','now')
             WHERE token=?
            """,
            (tg_user_id, username, first_name, last_name, token),
        )


def _sqlite_get_last_clicks(db_path: str, limit: int = 50) -> List[Dict[str, Any]]:
    with _sqlite_conn(db_path) as conn:
        cur = conn.execute(
            """
            SELECT token, ts, ip, user_agent, referrer,
                   tg_user_id, tg_username, tg_first_name, tg_last_name, linked_ts
              FROM clicks
          ORDER BY ts DESC
             LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


# -----------------------
# Postgres implementation
# -----------------------

def _pg_conn(db_url: str):
    if psycopg is None:
        raise RuntimeError("psycopg is not installed, but DATABASE_URL is set.")
    return psycopg.connect(db_url, row_factory=dict_row, autocommit=True)


def _pg_init_schema(db_url: str) -> None:
    with _pg_conn(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS clicks (
                    token TEXT PRIMARY KEY,
                    ts BIGINT NOT NULL,
                    ip TEXT,
                    user_agent TEXT,
                    referrer TEXT,
                    tg_user_id BIGINT,
                    tg_username TEXT,
                    tg_first_name TEXT,
                    tg_last_name TEXT,
                    linked_ts BIGINT
                );
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_clicks_ts ON clicks(ts DESC);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_clicks_tg_user_id ON clicks(tg_user_id);")


def _pg_insert_click(db_url: str, token: str, ts: int, ip: str, user_agent: str, referrer: str) -> None:
    with _pg_conn(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO clicks(token, ts, ip, user_agent, referrer)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (token) DO NOTHING
                """,
                (token, ts, ip, user_agent, referrer),
            )


def _pg_link_click_to_tg_user(
    db_url: str,
    token: str,
    tg_user_id: int,
    username: str = "",
    first_name: str = "",
    last_name: str = "",
) -> None:
    with _pg_conn(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE clicks
                   SET tg_user_id=%s,
                       tg_username=%s,
                       tg_first_name=%s,
                       tg_last_name=%s,
                       linked_ts=EXTRACT(EPOCH FROM NOW())::BIGINT
                 WHERE token=%s
                """,
                (tg_user_id, username, first_name, last_name, token),
            )


def _pg_get_last_clicks(db_url: str, limit: int = 50) -> List[Dict[str, Any]]:
    with _pg_conn(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT token, ts, ip, user_agent, referrer,
                       tg_user_id, tg_username, tg_first_name, tg_last_name, linked_ts
                  FROM clicks
              ORDER BY ts DESC
                 LIMIT %s
                """,
                (limit,),
            )
            return list(cur.fetchall())


# -----------------------
# Public API (DB-agnostic)
# -----------------------

def init_schema(track_db_path: str) -> None:
    kind, target = get_db_target(track_db_path)
    if kind == "postgres":
        _pg_init_schema(target)
    else:
        _sqlite_init_schema(target)


def insert_click(track_db_path: str, token: str, ts: int, ip: str, user_agent: str, referrer: str) -> None:
    kind, target = get_db_target(track_db_path)
    if kind == "postgres":
        _pg_insert_click(target, token, ts, ip, user_agent, referrer)
    else:
        _sqlite_insert_click(target, token, ts, ip, user_agent, referrer)


def link_click_to_tg_user(
    track_db_path: str,
    token: str,
    tg_user_id: int,
    username: str = "",
    first_name: str = "",
    last_name: str = "",
) -> None:
    kind, target = get_db_target(track_db_path)
    if kind == "postgres":
        _pg_link_click_to_tg_user(target, token, tg_user_id, username, first_name, last_name)
    else:
        _sqlite_link_click_to_tg_user(target, token, tg_user_id, username, first_name, last_name)


def get_last_clicks(track_db_path: str, limit: int = 50) -> List[Dict[str, Any]]:
    kind, target = get_db_target(track_db_path)
    if kind == "postgres":
        return _pg_get_last_clicks(target, limit)
    return _sqlite_get_last_clicks(target, limit)


def get_clicks_rows_for_csv(track_db_path: str, limit: int = 5000) -> List[Dict[str, Any]]:
    # Reuse same "last clicks" for CSV.
    return get_last_clicks(track_db_path, limit)
