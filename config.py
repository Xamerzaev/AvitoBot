from os import getenv
from dotenv import load_dotenv

load_dotenv()

TOKEN = getenv("BOT_TOKEN")
MODERATOR_CHAT_ID = getenv("ID_MODERATOR")
TELEGRAM_CHANNEL_ID = getenv("TELEGRAM_CHANNEL_ID")
