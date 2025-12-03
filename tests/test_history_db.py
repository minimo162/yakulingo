# tests/test_history_db.py
"""
Tests for the HistoryDB module.
"""

import pytest
import tempfile
from pathlib import Path

from yakulingo.storage.history_db import HistoryDB, get_default_db_path
from yakulingo.models.types import (
    HistoryEntry,
    TextTranslationResult,
    TranslationOption,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / 'test_history.db'
        db = HistoryDB(db_path)
        yield db
        db.close()  # Properly close database connection


@pytest.fixture
def sample_entry():
    """Create a sample history entry (bidirectional - no direction field)"""
    result = TextTranslationResult(
        source_text='Hello, world!',
        source_char_count=13,
        options=[
            TranslationOption(
                text='こんにちは、世界！',
                explanation='Standard translation'
            ),
            TranslationOption(
                text='やあ、世界！',
                explanation='Casual translation'
            ),
        ]
    )
    return HistoryEntry(
        source_text='Hello, world!',
        result=result,
    )


class TestHistoryDB:
    """Test cases for HistoryDB"""

    def test_init_creates_database(self):
        """Test that initialization creates the database file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / 'subdir' / 'test.db'
            db = HistoryDB(db_path)
            assert db_path.exists()

    def test_add_entry(self, temp_db, sample_entry):
        """Test adding an entry to the database"""
        entry_id = temp_db.add(sample_entry)
        assert entry_id == 1

    def test_get_recent(self, temp_db, sample_entry):
        """Test retrieving recent entries"""
        temp_db.add(sample_entry)
        entries = temp_db.get_recent(10)
        assert len(entries) == 1
        assert entries[0].source_text == sample_entry.source_text

    def test_get_recent_preserves_options(self, temp_db, sample_entry):
        """Test that options are preserved when retrieving"""
        temp_db.add(sample_entry)
        entries = temp_db.get_recent(10)
        assert len(entries[0].result.options) == 2
        assert entries[0].result.options[0].text == 'こんにちは、世界！'
        assert entries[0].result.options[1].text == 'やあ、世界！'

    def test_get_recent_order(self, temp_db):
        """Test that entries are returned in reverse chronological order"""
        for i in range(5):
            result = TextTranslationResult(
                source_text=f'Entry {i}',
                source_char_count=7,
                options=[TranslationOption(text=f'訳 {i}', explanation='')]
            )
            entry = HistoryEntry(
                source_text=f'Entry {i}',
                result=result,
            )
            temp_db.add(entry)

        entries = temp_db.get_recent(10)
        # Most recent (Entry 4) should be first
        assert entries[0].source_text == 'Entry 4'
        assert entries[-1].source_text == 'Entry 0'

    def test_get_recent_limit(self, temp_db):
        """Test that limit parameter works"""
        for i in range(10):
            result = TextTranslationResult(
                source_text=f'Entry {i}',
                source_char_count=7,
                options=[]
            )
            entry = HistoryEntry(
                source_text=f'Entry {i}',
                result=result,
            )
            temp_db.add(entry)

        entries = temp_db.get_recent(5)
        assert len(entries) == 5

    def test_get_by_id(self, temp_db, sample_entry):
        """Test retrieving entry by ID"""
        entry_id = temp_db.add(sample_entry)
        entry = temp_db.get_by_id(entry_id)
        assert entry is not None
        assert entry.source_text == sample_entry.source_text

    def test_get_by_id_not_found(self, temp_db):
        """Test retrieving non-existent entry"""
        entry = temp_db.get_by_id(9999)
        assert entry is None

    def test_delete(self, temp_db, sample_entry):
        """Test deleting an entry"""
        entry_id = temp_db.add(sample_entry)
        assert temp_db.get_count() == 1

        result = temp_db.delete(entry_id)
        assert result is True
        assert temp_db.get_count() == 0

    def test_delete_not_found(self, temp_db):
        """Test deleting non-existent entry"""
        result = temp_db.delete(9999)
        assert result is False

    def test_delete_by_timestamp(self, temp_db, sample_entry):
        """Test deleting an entry by timestamp"""
        temp_db.add(sample_entry)
        assert temp_db.get_count() == 1

        result = temp_db.delete_by_timestamp(sample_entry.timestamp)
        assert result is True
        assert temp_db.get_count() == 0

    def test_clear_all(self, temp_db, sample_entry):
        """Test clearing all entries"""
        for _ in range(5):
            temp_db.add(sample_entry)

        assert temp_db.get_count() == 5
        deleted = temp_db.clear_all()
        assert deleted == 5
        assert temp_db.get_count() == 0

    def test_search(self, temp_db):
        """Test searching entries"""
        result1 = TextTranslationResult(
            source_text='Hello world',
            source_char_count=11,
            options=[]
        )
        result2 = TextTranslationResult(
            source_text='Goodbye world',
            source_char_count=13,
            options=[]
        )

        temp_db.add(HistoryEntry(
            source_text='Hello world',
            result=result1,
        ))
        temp_db.add(HistoryEntry(
            source_text='Goodbye world',
            result=result2,
        ))

        results = temp_db.search('Hello')
        assert len(results) == 1
        assert results[0].source_text == 'Hello world'

        results = temp_db.search('world')
        assert len(results) == 2

    def test_get_count(self, temp_db, sample_entry):
        """Test counting entries"""
        assert temp_db.get_count() == 0

        temp_db.add(sample_entry)
        assert temp_db.get_count() == 1

        temp_db.add(sample_entry)
        assert temp_db.get_count() == 2

    def test_cleanup_old_entries(self, temp_db):
        """Test cleanup of old entries"""
        for i in range(20):
            result = TextTranslationResult(
                source_text=f'Entry {i}',
                source_char_count=7,
                options=[]
            )
            entry = HistoryEntry(
                source_text=f'Entry {i}',
                result=result,
            )
            temp_db.add(entry)

        assert temp_db.get_count() == 20

        deleted = temp_db.cleanup_old_entries(max_entries=10)
        assert deleted == 10
        assert temp_db.get_count() == 10

    def test_cleanup_no_action_when_under_limit(self, temp_db, sample_entry):
        """Test that cleanup does nothing when under limit"""
        for _ in range(5):
            temp_db.add(sample_entry)

        deleted = temp_db.cleanup_old_entries(max_entries=10)
        assert deleted == 0
        assert temp_db.get_count() == 5


class TestGetDefaultDbPath:
    """Test cases for get_default_db_path"""

    def test_returns_path(self):
        """Test that a Path object is returned"""
        path = get_default_db_path()
        assert isinstance(path, Path)

    def test_path_in_home_directory(self):
        """Test that path is in user's home directory"""
        path = get_default_db_path()
        assert str(Path.home()) in str(path)

    def test_path_includes_yakulingo(self):
        """Test that path includes .yakulingo directory"""
        path = get_default_db_path()
        assert '.yakulingo' in str(path)
