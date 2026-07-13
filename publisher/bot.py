import logging
import tempfile
from pathlib import Path

import httpx

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import BOT_TOKEN
import db

logger = logging.getLogger("publisher")

API_URL = "https://api.telegram.org/bot{token}/{method}"


def _api(method: str) -> str:
    return API_URL.format(token=BOT_TOKEN, method=method)


async def publish_to_channel(
    channel: str,
    text: str,
    media_path: str = "",
    media_type: str = "",
):
    target = channel if channel.startswith("@") else f"@{channel}"

    async with httpx.AsyncClient(timeout=60) as client:
        if media_type in ("photo", "video") and media_path:
            is_local = Path(media_path).exists()

            if is_local:
                await _send_local_media(client, target, text, media_path, media_type)
                return

            try:
                tmp = await _download_media(client, media_path, media_type)
                if tmp:
                    await _send_local_media(client, target, text, tmp, media_type)
                    Path(tmp).unlink(missing_ok=True)
                    return
            except Exception as e:
                logger.warning(f"Media send failed: {e}")

        await client.post(_api("sendMessage"), json={
            "chat_id": target,
            "text": text,
        })


async def _download_media(client: httpx.AsyncClient, url: str, media_type: str) -> str | None:
    resp = await client.get(url, follow_redirects=True)
    resp.raise_for_status()
    ext = ".jpg" if media_type == "photo" else ".mp4"
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    tmp.write(resp.content)
    tmp.close()
    return tmp.name


async def _send_local_media(client: httpx.AsyncClient, target: str, text: str, filepath: str, media_type: str):
    method = "sendPhoto" if media_type == "photo" else "sendVideo"
    file_field = "photo" if media_type == "photo" else "video"

    with open(filepath, "rb") as f:
        content = f.read()

    logger.info(f"Sending {media_type} to {target}, file={Path(filepath).name}, size={len(content)}")
    resp = await client.post(
        _api(method),
        data={"chat_id": target, "caption": text},
        files={file_field: (Path(filepath).name, content, "image/jpeg" if media_type == "photo" else "video/mp4")},
    )
    logger.info(f"Response: {resp.status_code} {resp.text[:200]}")

    data = resp.json()
    if not data.get("ok"):
        logger.error(f"Telegram error: {data}")
        raise Exception(f"Telegram API error: {data.get('description', 'unknown')}")
    logger.info(f"Published to {target}: msg {data['result'].get('message_id', '?')}")
