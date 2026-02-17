import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID: str = os.environ["TELEGRAM_CHAT_ID"]
KOBIS_API_KEY: str = os.environ["KOFIC_API_KEY"]
WATCHA_EMAIL: str = os.environ["WATCHA_EMAIL"]
WATCHA_PASSWORD: str = os.environ["WATCHA_PASSWORD"]

# Optional: LLM API keys for self-healing scraper (any one is sufficient)
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
HEALING_DB_PATH: str = os.environ.get("HEALING_DB_PATH", "data/strategies.db")

# Optional: Theater login credentials for booking
CGV_ID: str = os.environ.get("CGV_ID", "")
CGV_PASSWORD: str = os.environ.get("CGV_PASSWORD", "")
LOTTECINEMA_ID: str = os.environ.get("LOTTECINEMA_ID", "")
LOTTECINEMA_PASSWORD: str = os.environ.get("LOTTECINEMA_PASSWORD", "")
MEGABOX_ID: str = os.environ.get("MEGABOX_ID", "")
MEGABOX_PASSWORD: str = os.environ.get("MEGABOX_PASSWORD", "")
