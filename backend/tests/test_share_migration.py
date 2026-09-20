"""分享记录状态字段的旧库迁移测试"""
import sqlite3
import tempfile
from pathlib import Path


def test_init_db_adds_is_active_to_existing_share_table(monkeypatch):
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / 'legacy.db'

    conn = sqlite3.connect(db_path)
    conn.execute('''
        CREATE TABLE share_links (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            created_by TEXT NOT NULL,
            expires_at REAL,
            max_downloads INTEGER,
            download_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('''
        INSERT INTO share_links (id, file_id, created_by, expires_at, max_downloads)
        VALUES ('legacy-share', 'file-1', 'admin', NULL, 10)
    ''')
    conn.commit()
    conn.close()

    import database
    monkeypatch.setattr(database, 'DB_FILE', str(db_path))
    database.init_db()

    conn = sqlite3.connect(db_path)
    columns = [row[1] for row in conn.execute('PRAGMA table_info(share_links)').fetchall()]
    is_active = conn.execute(
        'SELECT is_active FROM share_links WHERE id = ?',
        ('legacy-share',)
    ).fetchone()[0]
    indexes = [row[1] for row in conn.execute('PRAGMA index_list(share_links)').fetchall()]
    conn.close()

    assert 'is_active' in columns
    assert is_active == 1
    assert 'idx_share_owner_active' in indexes
    assert 'idx_share_active' in indexes
