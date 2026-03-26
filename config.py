import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
GMAIL_CREDENTIALS_PATH: str = os.getenv("GMAIL_CREDENTIALS_PATH", "")
GMAIL_TOKEN_PATH: str = os.getenv("GMAIL_TOKEN_PATH", "./token.json")
GMAIL_REDIRECT_URI: str = os.getenv("GMAIL_REDIRECT_URI", "http://localhost:8000/auth/callback")
TARGET_EMAIL: str = os.getenv("TARGET_EMAIL", "inbox@focusgraphics.com")
POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "120"))
DB_PATH: str = os.getenv("DB_PATH", "./focusva.db")
