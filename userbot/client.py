import asyncio
import logging
from telethon import TelegramClient, events
from telethon.tl.types import (
    MessageMediaPhoto,
    MessageMediaDocument,
)
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, DATA_DIR
import db

logger = logging.getLogger("userbot")

client: TelegramClient | None = None

MEDIA_DIR = DATA_DIR / "media"
MEDIA_DIR.mkdir(exist_ok=True)


def get_client() -> TelegramClient:
    global client
    if client is None:
        client = TelegramClient("userbot_session", TELEGRAM_API_ID, TELEGRAM_API_HASH)
    return client


async def start_userbot():
    tg = get_client()
    await tg.start()
    logger.info("Userbot started")

    channels = await db.get_channels(active_only=True)
    channel_usernames = [ch["username"] for ch in channels]
    logger.info(f"Monitoring channels: {channel_usernames}")

    @tg.on(events.NewMessage(chats=channel_usernames))
    async def handler(event):
        await process_new_post(event)

    await tg.run_until_disconnected()


async def process_new_post(event):
    msg = event.message
    chat = await event.get_chat()
    username = chat.username or ""

    active_channels = await db.get_channels(active_only=True)
    active_usernames = {ch["username"] for ch in active_channels}
    if username not in active_usernames:
        return

    text = msg.message or ""
    media_type = ""
    media_path = ""

    if msg.media:
        tg = get_client()
        if isinstance(msg.media, MessageMediaPhoto):
            media_type = "photo"
            filename = f"{username}_{msg.id}.jpg"
            path = MEDIA_DIR / filename
            await tg.download_media(msg, file=str(path))
            media_path = str(path)
        elif isinstance(msg.media, MessageMediaDocument):
            doc = msg.media.document
            if doc.mime_type:
                if doc.mime_type.startswith("video"):
                    media_type = "video"
                    ext = doc.mime_type.split("/")[-1]
                    filename = f"{username}_{msg.id}.{ext}"
                elif doc.mime_type.startswith("image"):
                    media_type = "photo"
                    ext = doc.mime_type.split("/")[-1]
                    filename = f"{username}_{msg.id}.{ext}"
                else:
                    media_type = "document"
                    filename = f"{username}_{msg.id}"
            else:
                media_type = "document"
                filename = f"{username}_{msg.id}"

            path = MEDIA_DIR / filename
            await tg.download_media(msg, file=str(path))
            media_path = str(path)

    post_id = await db.add_post(
        channel_username=username,
        source_msg_id=msg.id,
        original_text=text,
        media_type=media_type,
        media_path=media_path,
    )

    if post_id:
        logger.info(f"New post #{post_id} from @{username} ({media_type or 'text'})")

        auto = await db.get_setting("auto_publish")
        if auto == "1":
            from publisher.paraphrase import paraphrase_and_publish
            asyncio.create_task(paraphrase_and_publish(post_id))


async def refresh_channel_list():
    channels = await db.get_channels(active_only=True)
    channel_usernames = [ch["username"] for ch in channels]
    logger.info(f"Updated monitoring: {channel_usernames}")
