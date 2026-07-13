import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

from config import BOT_TOKEN
import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("main")

PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")


async def run_scraper():
    from scraper import scrape_new_posts
    while True:
        interval = int(await db.get_setting("check_interval") or "60")
        logger.info(f"Scraping in {interval}s...")
        await scrape_new_posts()
        await asyncio.sleep(interval)


async def run_web():
    try:
        from web.app import app
        import uvicorn
        config = uvicorn.Config(app, host=HOST, port=PORT, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()
    except Exception as e:
        logger.error(f"Web panel error: {e}")


async def main():
    await db.get_db()
    logger.info("Database initialized")

    tasks = []

    tasks.append(asyncio.create_task(run_scraper()))
    logger.info("Scraper started (t.me/s/topor)")

    tasks.append(asyncio.create_task(run_web()))
    logger.info(f"Web panel starting at http://{HOST}:{PORT}")

    await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
