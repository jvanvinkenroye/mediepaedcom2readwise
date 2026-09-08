"""SQLite-Ablage fuer verarbeitete Artikel."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    article_id INTEGER PRIMARY KEY,
    landing_url TEXT NOT NULL,
    title TEXT NOT NULL,
    authors TEXT NOT NULL DEFAULT '[]',
    published TEXT,
    doi TEXT,
    language TEXT,
    abstract TEXT,
    pdf_url TEXT,
    html_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    readwise_pushed_at TEXT
);
"""


@dataclass
class ArticleRecord:
    article_id: int
    landing_url: str
    title: str
    authors: list[str]
    published: str | None
    doi: str | None
    language: str | None
    abstract: str | None
    pdf_url: str | None
    html_path: str | None
    status: str
    attempts: int
    last_error: str | None
    created_at: str
    updated_at: str
    readwise_pushed_at: str | None

    @property
    def doi_url(self) -> str | None:
        return f"https://doi.org/{self.doi}" if self.doi else None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _row_to_record(row: sqlite3.Row) -> ArticleRecord:
    data = dict(row)
    data["authors"] = json.loads(data["authors"])
    return ArticleRecord(**data)


class Store:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def known_ids(self) -> set[int]:
        rows = self._conn.execute("SELECT article_id FROM articles").fetchall()
        return {row["article_id"] for row in rows}

    def get(self, article_id: int) -> ArticleRecord | None:
        row = self._conn.execute(
            "SELECT * FROM articles WHERE article_id = ?", (article_id,)
        ).fetchone()
        return _row_to_record(row) if row else None

    def upsert_pending(self, article_id: int, landing_url: str, title: str) -> None:
        now = _now()
        self._conn.execute(
            """
            INSERT INTO articles
                (article_id, landing_url, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(article_id) DO NOTHING
            """,
            (article_id, landing_url, title, now, now),
        )
        self._conn.commit()

    def mark_done(
        self,
        article_id: int,
        *,
        title: str,
        authors: list[str],
        published: str | None,
        doi: str | None,
        language: str | None,
        abstract: str | None,
        pdf_url: str,
        html_path: str,
    ) -> None:
        self._conn.execute(
            """
            UPDATE articles SET title=?, authors=?, published=?, doi=?, language=?,
                abstract=?, pdf_url=?, html_path=?, status='done', last_error=NULL,
                updated_at=?
            WHERE article_id=?
            """,
            (
                title,
                json.dumps(authors, ensure_ascii=False),
                published,
                doi,
                language,
                abstract,
                pdf_url,
                html_path,
                _now(),
                article_id,
            ),
        )
        self._conn.commit()

    def mark_failed(self, article_id: int, error: str, max_attempts: int) -> None:
        record = self.get(article_id)
        attempts = (record.attempts if record else 0) + 1
        status = "failed" if attempts >= max_attempts else "pending"
        self._conn.execute(
            """
            UPDATE articles SET status=?, attempts=?, last_error=?, updated_at=?
            WHERE article_id=?
            """,
            (status, attempts, error[:2000], _now(), article_id),
        )
        self._conn.commit()

    def mark_pushed(self, article_id: int) -> None:
        self._conn.execute(
            "UPDATE articles SET readwise_pushed_at=?, updated_at=? WHERE article_id=?",
            (_now(), _now(), article_id),
        )
        self._conn.commit()

    def pending(self, limit: int) -> list[ArticleRecord]:
        rows = self._conn.execute(
            """
            SELECT * FROM articles WHERE status='pending'
            ORDER BY article_id ASC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_record(r) for r in rows]

    def done(self, limit: int) -> list[ArticleRecord]:
        rows = self._conn.execute(
            """
            SELECT * FROM articles WHERE status='done'
            ORDER BY COALESCE(published, '') DESC, article_id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_record(r) for r in rows]

    def unpushed(self) -> list[ArticleRecord]:
        rows = self._conn.execute(
            """
            SELECT * FROM articles
            WHERE status='done' AND readwise_pushed_at IS NULL
            ORDER BY article_id ASC
            """
        ).fetchall()
        return [_row_to_record(r) for r in rows]
