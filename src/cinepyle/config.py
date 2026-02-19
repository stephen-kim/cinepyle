import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID: str = os.environ["TELEGRAM_CHAT_ID"]
KOBIS_API_KEY: str = os.environ["KOFIC_API_KEY"]
WATCHA_EMAIL: str = os.environ["WATCHA_EMAIL"]
WATCHA_PASSWORD: str = os.environ["WATCHA_PASSWORD"]

# Cinema chain login credentials (optional — for booking history)
CGV_ID: str = os.environ.get("CGV_ID", "")
CGV_PASSWORD: str = os.environ.get("CGV_PASSWORD", "")
LOTTE_ID: str = os.environ.get("LOTTE_ID", "")
LOTTE_PASSWORD: str = os.environ.get("LOTTE_PASSWORD", "")
MEGABOX_ID: str = os.environ.get("MEGABOX_ID", "")
MEGABOX_PASSWORD: str = os.environ.get("MEGABOX_PASSWORD", "")

# Dashboard (optional)
DASHBOARD_PORT: int = int(os.environ.get("DASHBOARD_PORT", "8080"))
