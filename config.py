import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "bot.db"

TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8000"))
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

DEFAULT_PARAPHRASE_PROMPT = (
    "Перефразируй следующий текст. Сохрани ключевую информацию и смысл. "
    "Сделай стиль slightly другим, но оставь тот же формат и тон. "
    "Не добавляй ничего нового. Верни только перефразированный текст без комментариев."
)
