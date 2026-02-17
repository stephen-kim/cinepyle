import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID: str = os.environ["TELEGRAM_CHAT_ID"]
KOBIS_API_KEY: str = os.environ["KOBIS_API_KEY"]
WATCHA_EMAIL: str = os.environ["WATCHA_EMAIL"]
WATCHA_PASSWORD: str = os.environ["WATCHA_PASSWORD"]
