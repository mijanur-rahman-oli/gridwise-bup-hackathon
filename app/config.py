"""Centralised configuration — reads env vars, never logs secrets."""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "groq")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    LLM_TIMEOUT_SECONDS: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "15"))
    REQUEST_TIMEOUT_SECONDS: int = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "25"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    @classmethod
    def has_llm(cls) -> bool:
        return bool(cls.LLM_API_KEY)


settings = Settings()