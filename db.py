import aiosqlite
from config import DB_PATH

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(str(DB_PATH))
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
        await init_db(_db)
    return _db


async def init_db(db: aiosqlite.Connection):
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            title TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_username TEXT NOT NULL,
            source_msg_id INTEGER NOT NULL,
            original_text TEXT DEFAULT '',
            paraphrased_text TEXT DEFAULT '',
            media_type TEXT DEFAULT '',
            media_path TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            error TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            published_at TIMESTAMP,
            UNIQUE(channel_username, source_msg_id)
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
        CREATE INDEX IF NOT EXISTS idx_posts_channel ON posts(channel_username);
    """)

    defaults = {
        "paraphrase_prompt": (
            "Перефразируй следующий текст. Сохрани ключевую информацию и смысл. "
            "Сделай стиль slightly другим, но оставь тот же формат и тон. "
            "Не добавляй ничего нового. Верни только перефразированный текст без комментариев."
        ),
        "auto_publish": "0",
        "target_channel": "",
        "check_interval": "60",
    }
    for key, value in defaults.items():
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    await db.commit()


async def get_setting(key: str) -> str:
    db = await get_db()
    cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row["value"] if row else ""


async def set_setting(key: str, value: str):
    db = await get_db()
    await db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
        (key, value, value),
    )
    await db.commit()


async def add_channel(username: str, title: str = "") -> bool:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO channels (username, title) VALUES (?, ?)",
            (username.lstrip("@"), title),
        )
        await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def remove_channel(username: str):
    db = await get_db()
    await db.execute("DELETE FROM channels WHERE username = ?", (username.lstrip("@"),))
    await db.commit()


async def toggle_channel(username: str):
    db = await get_db()
    await db.execute(
        "UPDATE channels SET active = 1 - active WHERE username = ?",
        (username.lstrip("@"),),
    )
    await db.commit()


async def get_channels(active_only: bool = False) -> list[dict]:
    db = await get_db()
    q = "SELECT * FROM channels"
    if active_only:
        q += " WHERE active = 1"
    q += " ORDER BY created_at DESC"
    cursor = await db.execute(q)
    return [dict(row) for row in await cursor.fetchall()]


async def add_post(
    channel_username: str,
    source_msg_id: int,
    original_text: str = "",
    media_type: str = "",
    media_path: str = "",
) -> int | None:
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO posts (channel_username, source_msg_id, original_text, media_type, media_path) "
            "VALUES (?, ?, ?, ?, ?)",
            (channel_username, source_msg_id, original_text, media_type, media_path),
        )
        await db.commit()
        return cursor.lastrowid
    except aiosqlite.IntegrityError:
        return None


async def update_post(post_id: int, **kwargs):
    db = await get_db()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [post_id]
    await db.execute(f"UPDATE posts SET {sets} WHERE id = ?", vals)
    await db.commit()


async def get_posts(status: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    db = await get_db()
    q = "SELECT * FROM posts"
    params: list = []
    if status:
        q += " WHERE status = ?"
        params.append(status)
    q += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor = await db.execute(q, params)
    return [dict(row) for row in await cursor.fetchall()]


async def get_post(post_id: int) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_stats() -> dict:
    db = await get_db()
    stats = {}
    cursor = await db.execute("SELECT COUNT(*) as cnt FROM channels")
    stats["channels"] = (await cursor.fetchone())["cnt"]

    cursor = await db.execute("SELECT COUNT(*) as cnt FROM posts")
    stats["total_posts"] = (await cursor.fetchone())["cnt"]

    cursor = await db.execute("SELECT COUNT(*) as cnt FROM posts WHERE status = 'published'")
    stats["published"] = (await cursor.fetchone())["cnt"]

    cursor = await db.execute("SELECT COUNT(*) as cnt FROM posts WHERE status = 'pending'")
    stats["pending"] = (await cursor.fetchone())["cnt"]

    cursor = await db.execute("SELECT COUNT(*) as cnt FROM posts WHERE status = 'skipped'")
    stats["skipped"] = (await cursor.fetchone())["cnt"]

    cursor = await db.execute(
        "SELECT channel_username, COUNT(*) as cnt FROM posts WHERE status = 'published' "
        "GROUP BY channel_username ORDER BY cnt DESC LIMIT 10"
    )
    stats["by_channel"] = [dict(row) for row in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT date(created_at) as day, COUNT(*) as cnt FROM posts "
        "WHERE status = 'published' GROUP BY day ORDER BY day DESC LIMIT 14"
    )
    stats["by_day"] = [dict(row) for row in await cursor.fetchall()]

    return stats
