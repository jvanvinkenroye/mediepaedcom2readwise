"""SQLite-Ablage fuer verarbeitete Artikel, geschluesselt nach Quelle und ID."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    source TEXT NOT NULL,
    article_id INTEGER NOT NULL,
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
    readwise_pushed_at TEXT,
    PRIMARY KEY (source, article_id)
);
"""

# Version 1 hatte keinen Quellen-Schluessel; alle Zeilen stammten von medienpaed.
LEGACY_SOURCE = "medienpaed"


@dataclass
class ArticleRecord:
    source: str
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
        self._migrate()

    def _migrate(self) -> None:
        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(articles)").fetchall()
        }
        if columns and "source" not in columns:
            # Tabelle aus Version 1: Primaerschluessel aendern geht nur per Neuaufbau.
            self._conn.executescript(
                "ALTER TABLE articles RENAME TO articles_v1;"
                + SCHEMA
                + f"""
                INSERT INTO articles
                SELECT '{LEGACY_SOURCE}', article_id, landing_url, title, authors,
                       published, doi, language, abstract, pdf_url, html_path,
                       status, attempts, last_error, created_at, updated_at,
                       readwise_pushed_at
                FROM articles_v1;
                DROP TABLE articles_v1;
                """
            )
        else:
            self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def known_ids(self, source: str) -> set[int]:
        rows = self._conn.execute(
            "SELECT article_id FROM articles WHERE source = ?", (source,)
        ).fetchall()
        return {row["article_id"] for row in rows}

    def get(self, source: str, article_id: int) -> ArticleRecord | None:
        row = self._conn.execute(
            "SELECT * FROM articles WHERE source = ? AND article_id = ?",
            (source, article_id),
        ).fetchone()
        return _row_to_record(row) if row else None

    def upsert_pending(
        self, source: str, article_id: int, landing_url: str, title: str
    ) -> None:
        now = _now()
        self._conn.execute(
            """
            INSERT INTO articles
                (source, article_id, landing_url, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, article_id) DO NOTHING
            """,
            (source, article_id, landing_url, title, now, now),
        )
        self._conn.commit()

    def mark_done(
        self,
        source: str,
        article_id: int,
        *,
        title: str,
        authors: list[str],
        published: str | None,
        doi: str | None,
        language: str | None,
        abstract: str | None,
        pdf_url: str | None,
        html_path: str,
    ) -> None:
        self._conn.execute(
            """
            UPDATE articles SET title=?, authors=?, published=?, doi=?, language=?,
                abstract=?, pdf_url=?, html_path=?, status='done', last_error=NULL,
                updated_at=?
            WHERE source=? AND article_id=?
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
                source,
                article_id,
            ),
        )
        self._conn.commit()

    def mark_failed(
        self, source: str, article_id: int, error: str, max_attempts: int
    ) -> None:
        record = self.get(source, article_id)
        attempts = (record.attempts if record else 0) + 1
        status = "failed" if attempts >= max_attempts else "pending"
        self._conn.execute(
            """
            UPDATE articles SET status=?, attempts=?, last_error=?, updated_at=?
            WHERE source=? AND article_id=?
            """,
            (status, attempts, error[:2000], _now(), source, article_id),
        )
        self._conn.commit()

    def reset(self, source: str, article_id: int) -> bool:
        """Artikel erneut zur Verarbeitung freigeben (z. B. PDF nachgereicht)."""
        cursor = self._conn.execute(
            """
            UPDATE articles SET status='pending', attempts=0, last_error=NULL,
                updated_at=?
            WHERE source=? AND article_id=?
            """,
            (_now(), source, article_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def mark_pushed(self, source: str, article_id: int) -> None:
        self._conn.execute(
            """
            UPDATE articles SET readwise_pushed_at=?, updated_at=?
            WHERE source=? AND article_id=?
            """,
            (_now(), _now(), source, article_id),
        )
        self._conn.commit()

    def pending(self, limit: int) -> list[ArticleRecord]:
        rows = self._conn.execute(
            """
            SELECT * FROM articles WHERE status='pending'
            ORDER BY source, article_id ASC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_record(r) for r in rows]

    def done(self, limit: int, source: str | None = None) -> list[ArticleRecord]:
        where = "status='done'" + (" AND source=?" if source else "")
        params: tuple = (source, limit) if source else (limit,)
        rows = self._conn.execute(
            f"""
            SELECT * FROM articles WHERE {where}
            ORDER BY COALESCE(published, '') DESC, article_id DESC LIMIT ?
            """,
            params,
        ).fetchall()
        return [_row_to_record(r) for r in rows]

    def unpushed(self) -> list[ArticleRecord]:
        rows = self._conn.execute(
            """
            SELECT * FROM articles
            WHERE status='done' AND readwise_pushed_at IS NULL
            ORDER BY source, article_id ASC
            """
        ).fetchall()
        return [_row_to_record(r) for r in rows]

    def counts(self) -> list[tuple[str, str, int]]:
        rows = self._conn.execute(
            """
            SELECT source, status, COUNT(*) AS n FROM articles
            GROUP BY source, status ORDER BY source, status
            """
        ).fetchall()
        return [(r["source"], r["status"], r["n"]) for r in rows]
