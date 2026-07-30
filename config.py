import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def reload_dotenv():
    load_dotenv(override=True)


class Config:
    API_BASE_URL: str = ""
    API_KEY: str = ""
    MODEL_NAME: str = ""
    SAVE_DIR: str = "./saves"

    @classmethod
    def load(cls):
        reload_dotenv()
        cls.API_BASE_URL = os.getenv("API_BASE_URL", "").rstrip("/")
        cls.API_KEY = os.getenv("API_KEY", "")
        cls.MODEL_NAME = os.getenv("MODEL_NAME", "")
        cls.SAVE_DIR = os.getenv("SAVE_DIR", "./saves")

        if cls.API_BASE_URL:
            if "/chat/completions" in cls.API_BASE_URL:
                cls.API_BASE_URL = cls.API_BASE_URL.replace("/chat/completions", "")

        if not cls.MODEL_NAME:
            cls.MODEL_NAME = cls._detect_model(cls.API_BASE_URL)

        Path(cls.SAVE_DIR).mkdir(parents=True, exist_ok=True)

    @classmethod
    def _detect_model(cls, base_url: str) -> str:
        url = base_url.lower()
        if "openai" in url:
            return "gpt-4o"
        if "deepseek" in url:
            return "deepseek-chat"
        if "anthropic" in url or "claude" in url:
            return "claude-sonnet-4-20250514"
        if "groq" in url:
            return "llama-3.3-70b-versatile"
        if "googleapis" in url or "gemini" in url:
            return "gemini-2.0-flash"
        return "deepseek-chat"

    @classmethod
    def is_ready(cls) -> bool:
        return bool(cls.API_BASE_URL and cls.API_KEY)
