# yakulingo/storage/history_db.py
"""
SQLite-based persistent storage for translation history.
Inspired by Nani Translate's local-first approach.
"""

import sqlite3
import json
from pathlib import Path
from typing import Optional
from datetime import datetime

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
    """

    # Database configuration
    DB_TIMEOUT = 30.0  # Connection timeout in seconds

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or get_default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        """Create a database connection with timeout."""
        return sqlite3.connect(self.db_path, timeout=self.DB_TIMEOUT)

    def _init_db(self):
        """Initialize database schema"""
        with self._connect() as conn:
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

        with self._connect() as conn:
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
        with self._connect() as conn:
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
        with self._connect() as conn:
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
        with self._connect() as conn:
            cursor = conn.execute(
                'DELETE FROM history WHERE id = ?',
                (entry_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_by_timestamp(self, timestamp: str) -> bool:
        """Delete a history entry by timestamp"""
        with self._connect() as conn:
            cursor = conn.execute(
                'DELETE FROM history WHERE timestamp = ?',
                (timestamp,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def clear_all(self) -> int:
        """Clear all history entries. Returns number of deleted entries."""
        with self._connect() as conn:
            cursor = conn.execute('DELETE FROM history')
            conn.commit()
            return cursor.rowcount

    def search(self, query: str, limit: int = 20) -> list[HistoryEntry]:
        """Search history by source text"""
        with self._connect() as conn:
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
        with self._connect() as conn:
            result = conn.execute('SELECT COUNT(*) FROM history').fetchone()
            return result[0] if result else 0

    def cleanup_old_entries(self, max_entries: int = 500) -> int:
        """
        Remove old entries to keep database size manageable.
        Returns number of deleted entries.
        """
        with self._connect() as conn:
            # Get count
            count = conn.execute('SELECT COUNT(*) FROM history').fetchone()[0]

            if count <= max_entries:
                return 0

            # Delete oldest entries
            to_delete = count - max_entries
            cursor = conn.execute(
                '''
                DELETE FROM history
                WHERE id IN (
                    SELECT id FROM history
                    ORDER BY timestamp ASC
                    LIMIT ?
                )
                ''',
                (to_delete,)
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
