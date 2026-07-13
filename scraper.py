import re
import logging
import html as html_mod
from pathlib import Path

import httpx

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DATA_DIR
import db

logger = logging.getLogger("scraper")

CHANNEL_URL = "https://t.me/s/topor"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
MEDIA_DIR = DATA_DIR / "media"
MEDIA_DIR.mkdir(exist_ok=True)


def fetch_page(url: str) -> str:
    resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def download_media(url: str, channel: str, msg_id: int, media_type: str) -> str:
    ext = ".jpg" if media_type == "photo" else ".mp4"
    filename = f"{channel}_{msg_id}{ext}"
    filepath = MEDIA_DIR / filename
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        if len(resp.content) < 1000:
            logger.warning(f"Media too small ({len(resp.content)} bytes), skipping: {url[:80]}")
            return ""
        filepath.write_bytes(resp.content)
        logger.info(f"Downloaded {media_type}: {filename} ({len(resp.content)} bytes)")
        return str(filepath)
    except Exception as e:
        logger.error(f"Download failed {url[:80]}: {e}")
        return ""


def parse_posts(html: str) -> list[dict]:
    posts = []
    seen = set()

    post_ids = re.findall(r'data-post="([^"]+)"', html)
    unique_ids = list(dict.fromkeys(post_ids))

    for post_id in unique_ids:
        if post_id in seen:
            continue
        seen.add(post_id)

        start = html.find(f'data-post="{post_id}"')
        if start == -1:
            continue

        next_post = html.find('data-post=', start + 20)
        end_section = html.find('</div>\n</div>\n</div>', start + 20)
        if end_section == -1:
            end_section = html.find('js-widget_message_wrap', start + 20)
        if next_post > start and end_section > start:
            end = min(next_post, end_section)
        elif next_post > start:
            end = next_post
        elif end_section > start:
            end = end_section
        else:
            end = min(start + 5000, len(html))
        block = html[start:end]

        text = ""
        text_m = re.search(
            r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            block,
            re.DOTALL,
        )
        if text_m:
            raw = text_m.group(1)
            raw = re.sub(r"<br\s*/?>", "\n", raw)
            raw = re.sub(r"<[^>]+>", " ", raw)
            raw = html_mod.unescape(raw)
            text = " ".join(raw.split()).strip()

        media_type = ""
        media_url = ""

        if "tgme_widget_message_photo_wrap" in block:
            media_type = "photo"
            url_m = re.search(r"background-image:url\('([^']+)'\)", block)
            if url_m:
                media_url = url_m.group(1)

        if "tgme_widget_message_video_thumb" in block or "<video " in block:
            media_type = "video"
            url_m = re.search(r"background-image:url\('([^']+)'\)", block)
            if url_m:
                media_url = url_m.group(1)

        views_m = re.search(r'class="tgme_widget_message_views"[^>]*>([^<]+)<', block)
        views = views_m.group(1).strip() if views_m else ""

        time_m = re.search(r'datetime="([^"]+)"', block)
        dt = time_m.group(1) if time_m else ""

        posts.append({
            "post_id": post_id,
            "text": text,
            "media_type": media_type,
            "media_url": media_url,
            "views": views,
            "datetime": dt,
            "link": f"https://t.me/{post_id}",
        })

    return posts


async def scrape_new_posts():
    try:
        html = fetch_page(CHANNEL_URL)
        posts = parse_posts(html)
        logger.info(f"Parsed {len(posts)} posts from {CHANNEL_URL}")

        new_count = 0
        for p in posts:
            parts = p["post_id"].split("/")
            if len(parts) != 2:
                continue
            channel, msg_id_str = parts
            try:
                msg_id = int(msg_id_str)
            except ValueError:
                continue

            media_path = p["media_url"]
            if media_path and p["media_type"]:
                local = download_media(media_path, channel, msg_id, p["media_type"])
                if local:
                    media_path = local

            result = await db.add_post(
                channel_username=channel,
                source_msg_id=msg_id,
                original_text=p["text"],
                media_type=p["media_type"],
                media_path=media_path,
            )
            if result:
                new_count += 1
                logger.info(f"New post #{result} from @{channel} (msg {msg_id})")

                auto = await db.get_setting("auto_publish")
                if auto == "1":
                    from publisher.paraphrase import paraphrase_and_publish
                    import asyncio
                    asyncio.create_task(paraphrase_and_publish(result))

        logger.info(f"Scrape done: {new_count} new posts")
        return new_count

    except Exception as e:
        logger.error(f"Scrape error: {e}")
        return 0
