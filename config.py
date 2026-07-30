import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Config:
    API_BASE_URL: str = ""
    API_KEY: str = ""
    MODEL_NAME: str = ""
    SAVE_DIR: str = "./saves"

    @classmethod
    def load(cls):
        cls.API_BASE_URL = os.getenv("API_BASE_URL", "").rstrip("/")
        cls.API_KEY = os.getenv("API_KEY", "")
        cls.MODEL_NAME = os.getenv("MODEL_NAME", "")
        cls.SAVE_DIR = os.getenv("SAVE_DIR", "./saves")

        if cls.API_BASE_URL:
            if "/chat/completions" in cls.API_BASE_URL:
                cls.API_BASE_URL = cls.API_BASE_URL.replace("/chat/completions", "")

        Path(cls.SAVE_DIR).mkdir(parents=True, exist_ok=True)

    @classmethod
    def is_ready(cls) -> bool:
        return bool(cls.API_BASE_URL and cls.API_KEY and cls.MODEL_NAME)
