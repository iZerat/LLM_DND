import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def reload_dotenv():
    load_dotenv(override=True)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


class Config:
    API_BASE_URL: str = ""
    API_KEY: str = ""
    MODEL_NAME: str = ""
    SAVE_DIR: str = "./saves"
    # 资源创建管线（DM 查表 → 重试 n 次 → 是否允许回退填表创建）：
    RESOURCE_LOOKUP_RETRIES: int = 2   # 本地目录未命中时允许重试的次数
    ALLOW_FREE_CREATE: bool = False
    DEBUG_DM: bool = False       # true=让我（opencode）当DM，调试用    # 重试 n 次仍未命中后，是否允许凭空填表创建
    # 块缺失补写（事件/选择等关键块缺失时向 LLM 发起补写请求）：
    REPAIR_MAX_RETRIES: int = 3          # 一次 dm_call 内最多补写重试次数
    REPAIR_TOKEN_BUDGET: int = 100000    # 本次 dm_call 累计消耗 token 阈值，超过即停止补写

    @classmethod
    def load(cls):
        reload_dotenv()
        cls.API_BASE_URL = os.getenv("API_BASE_URL", "").rstrip("/")
        cls.API_KEY = os.getenv("API_KEY", "")
        cls.MODEL_NAME = os.getenv("MODEL_NAME", "")
        cls.SAVE_DIR = os.getenv("SAVE_DIR", "./saves")
        cls.RESOURCE_LOOKUP_RETRIES = _env_int("RESOURCE_LOOKUP_RETRIES", 2)
        cls.ALLOW_FREE_CREATE = os.getenv("ALLOW_FREE_CREATE", "").strip().lower() in (
            "1", "true", "yes", "on",
        )
        cls.DEBUG_DM = os.getenv("DEBUG_DM", "").strip().lower() in (
            "1", "true", "yes", "on",
        )
        cls.REPAIR_MAX_RETRIES = _env_int("REPAIR_MAX_RETRIES", 3)
        cls.REPAIR_TOKEN_BUDGET = _env_int("REPAIR_TOKEN_BUDGET", 100000)

        if cls.API_BASE_URL:
            if "/chat/completions" in cls.API_BASE_URL:
                cls.API_BASE_URL = cls.API_BASE_URL.replace("/chat/completions", "")

        if not cls.MODEL_NAME:
            cls.MODEL_NAME = cls._detect_model(cls.API_BASE_URL)

        Path(cls.SAVE_DIR).mkdir(parents=True, exist_ok=True)

    @classmethod
    def _detect_model(cls, base_url: str) -> str:
        url = base_url.lower()
        if "deepseek" in url:
            return "deepseek-v4-pro"
        if "openai" in url:
            return "gpt-4o"
        if "anthropic" in url or "claude" in url:
            return "claude"
        if "groq" in url:
            return "llama"
        if "googleapis" in url or "gemini" in url:
            return "gemini"
        return "other"

    @classmethod
    def is_ready(cls) -> bool:
        return bool(cls.API_BASE_URL and cls.API_KEY)
