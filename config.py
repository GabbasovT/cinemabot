import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SSPOISK_API_KEY = os.getenv("SSPOISK_API_KEY")
DB_URL = os.getenv("DATABASE_URL")
