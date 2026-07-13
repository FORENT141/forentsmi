import logging
import httpx
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import OPENAI_API_KEY, OPENAI_MODEL
import db

logger = logging.getLogger("paraphrase")


async def paraphrase_text(text: str) -> str:
    api_key = await db.get_setting("openai_api_key") or OPENAI_API_KEY
    if not api_key or not text.strip() or api_key.startswith("sk-test"):
        return text

    model = await db.get_setting("openai_model") or OPENAI_MODEL
    prompt = await db.get_setting("paraphrase_prompt")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": text},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 2000,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Paraphrase error: {e}")
        return text


async def paraphrase_and_publish(post_id: int):
    from datetime import datetime as dt
    from publisher.bot import publish_to_channel

    post = await db.get_post(post_id)
    if not post:
        return

    target = await db.get_setting("target_channel")
    if not target:
        return

    text = post["paraphrased_text"] or await paraphrase_text(post["original_text"])

    await db.update_post(post_id, paraphrased_text=text, status="publishing")
    try:
        await publish_to_channel(
            channel=target,
            text=text,
            media_path=post["media_path"],
            media_type=post["media_type"],
        )
        await db.update_post(post_id, status="published", published_at=dt.utcnow().isoformat())
    except Exception as e:
        logger.error(f"Publish error for post #{post_id}: {e}")
        await db.update_post(post_id, status="error", error=str(e))
