# yakulingo/storage/history_db.py
"""
SQLite-based persistent storage for translation history.
Inspired by Nani Translate's local-first approach.
"""

import sqlite3
import json
import threading
from pathlib import Path
from typing import Optional

from yakulingo.models.types import (
    HistoryEntry,
    TextTranslationResult,
    TranslationOption,
)


def get_default_db_path() -> Path:
    """Get default database path in user's home directory"""
    db_dir = Path.home() / '.yakulingo'
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / 'history.db'


class HistoryDB:
    """
    SQLite database for storing translation history.
    Data is stored locally on user's device for privacy.

    Uses connection pooling for better performance.
    """

    # Database configuration
    DB_TIMEOUT = 30.0  # Connection timeout in seconds

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or get_default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Thread-local storage for connections (one per thread)
        self._local = threading.local()
        self._lock = threading.Lock()

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """
        Get a database connection for the current thread.
        Reuses existing connection if available (connection pooling).
        """
        conn = getattr(self._local, 'connection', None)
        if conn is None:
            conn = sqlite3.connect(
                self.db_path,
                timeout=self.DB_TIMEOUT,
                check_same_thread=False
            )
            # Enable WAL mode for better concurrent read performance
            conn.execute('PRAGMA journal_mode=WAL')
            # Enable foreign keys
            conn.execute('PRAGMA foreign_keys=ON')
            self._local.connection = conn
        return conn

    def close(self):
        """Close the connection for the current thread."""
        conn = getattr(self._local, 'connection', None)
        if conn is not None:
            conn.close()
            self._local.connection = None

    def _init_db(self):
        """Initialize database schema"""
        conn = self._get_connection()
        with self._lock:
            # Create table with backward-compatible schema
            # (direction column kept for backward compatibility with existing DBs)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_text TEXT NOT NULL,
                    direction TEXT DEFAULT 'bidirectional',
                    result_json TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Create index for faster timestamp-based queries
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_history_timestamp
                ON history(timestamp DESC)
            ''')
            # Create index for search queries
            # Note: LIKE '%query%' won't use index, but LIKE 'query%' will
            # This index helps with prefix searches and sorting during search
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_history_source_text
                ON history(source_text COLLATE NOCASE)
            ''')
            conn.commit()

    def add(self, entry: HistoryEntry) -> int:
        """
        Add entry to history.
        Returns the ID of the inserted entry.
        """
        result_json = self._serialize_result(entry.result)
        conn = self._get_connection()

        with self._lock:
            cursor = conn.execute(
                '''
                INSERT INTO history (source_text, direction, result_json, timestamp)
                VALUES (?, ?, ?, ?)
                ''',
                (
                    entry.source_text,
                    'bidirectional',  # Always bidirectional now
                    result_json,
                    entry.timestamp,
                )
            )
            conn.commit()
            return cursor.lastrowid

    def get_recent(self, limit: int = 50) -> list[HistoryEntry]:
        """Get most recent history entries"""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''
            SELECT id, source_text, direction, result_json, timestamp
            FROM history
            ORDER BY timestamp DESC
            LIMIT ?
            ''',
            (limit,)
        ).fetchall()

        return [self._row_to_entry(row) for row in rows]

    def get_by_id(self, entry_id: int) -> Optional[HistoryEntry]:
        """Get a specific history entry by ID"""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            '''
            SELECT id, source_text, direction, result_json, timestamp
            FROM history
            WHERE id = ?
            ''',
            (entry_id,)
        ).fetchone()

        return self._row_to_entry(row) if row else None

    def delete(self, entry_id: int) -> bool:
        """Delete a history entry"""
        conn = self._get_connection()
        with self._lock:
            cursor = conn.execute(
                'DELETE FROM history WHERE id = ?',
                (entry_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_by_timestamp(self, timestamp: str) -> bool:
        """Delete a history entry by timestamp"""
        conn = self._get_connection()
        with self._lock:
            cursor = conn.execute(
                'DELETE FROM history WHERE timestamp = ?',
                (timestamp,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def clear_all(self) -> int:
        """Clear all history entries. Returns number of deleted entries."""
        conn = self._get_connection()
        with self._lock:
            cursor = conn.execute('DELETE FROM history')
            conn.commit()
            return cursor.rowcount

    def search(self, query: str, limit: int = 20) -> list[HistoryEntry]:
        """Search history by source text"""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''
            SELECT id, source_text, direction, result_json, timestamp
            FROM history
            WHERE source_text LIKE ?
            ORDER BY timestamp DESC
            LIMIT ?
            ''',
            (f'%{query}%', limit)
        ).fetchall()

        return [self._row_to_entry(row) for row in rows]

    def get_count(self) -> int:
        """Get total number of history entries"""
        conn = self._get_connection()
        result = conn.execute('SELECT COUNT(*) FROM history').fetchone()
        return result[0] if result else 0

    def cleanup_old_entries(self, max_entries: int = 500) -> int:
        """
        Remove old entries to keep database size manageable.
        Returns number of deleted entries.

        Optimized: Uses single query instead of count + delete.
        """
        conn = self._get_connection()
        with self._lock:
            # Single query: delete entries not in the most recent max_entries
            cursor = conn.execute(
                '''
                DELETE FROM history
                WHERE id NOT IN (
                    SELECT id FROM history
                    ORDER BY timestamp DESC
                    LIMIT ?
                )
                ''',
                (max_entries,)
            )
            conn.commit()
            return cursor.rowcount

    def _serialize_result(self, result: TextTranslationResult) -> str:
        """Serialize TextTranslationResult to JSON"""
        data = {
            'source_text': result.source_text,
            'source_char_count': result.source_char_count,
            'output_language': result.output_language,
            'options': [
                {
                    'text': opt.text,
                    'explanation': opt.explanation,
                    'char_count': opt.char_count,
                }
                for opt in result.options
            ],
            'error_message': result.error_message,
        }
        return json.dumps(data, ensure_ascii=False)

    def _deserialize_result(self, json_str: str) -> TextTranslationResult:
        """Deserialize JSON to TextTranslationResult"""
        data = json.loads(json_str)
        options = [
            TranslationOption(
                text=opt['text'],
                explanation=opt['explanation'],
                char_count=opt.get('char_count', 0),
            )
            for opt in data.get('options', [])
        ]
        return TextTranslationResult(
            source_text=data['source_text'],
            source_char_count=data.get('source_char_count', 0),
            output_language=data.get('output_language', 'en'),
            options=options,
            error_message=data.get('error_message'),
        )

    def _row_to_entry(self, row: sqlite3.Row) -> HistoryEntry:
        """Convert database row to HistoryEntry"""
        result = self._deserialize_result(row['result_json'])
        return HistoryEntry(
            source_text=row['source_text'],
            result=result,
            timestamp=row['timestamp'],
        )
