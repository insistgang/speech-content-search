from contextlib import contextmanager
from pathlib import Path
import sqlite3


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS videos (
                    id TEXT PRIMARY KEY, file_name TEXT NOT NULL, path TEXT UNIQUE NOT NULL,
                    duration_seconds REAL, size_bytes INTEGER, format TEXT,
                    status TEXT NOT NULL, error_message TEXT, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, video_id TEXT REFERENCES videos(id) ON DELETE CASCADE,
                    status TEXT NOT NULL, progress INTEGER NOT NULL, error_message TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS segments (
                    id INTEGER PRIMARY KEY, video_id TEXT REFERENCES videos(id) ON DELETE CASCADE,
                    start_ms INTEGER, end_ms INTEGER, text TEXT NOT NULL, source TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS keyword_sets (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, terms TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS segments_video ON segments(video_id);
            ''')

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def query(self, sql, parameters=()):
        with self.connection() as connection:
            return [dict(row) for row in connection.execute(sql, parameters).fetchall()]
