"""Configuration for Telegram Prompt Lab Bot.

All secrets are loaded from `.env`. Never commit real tokens to GitHub.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


PROJECT_ROOT = Path(__file__).resolve().parent


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    bot_token: str = os.getenv("BOT_TOKEN", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")

    # The homework example uses this exact model. You can replace it in .env.
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5-mini-2025-08-07")

    # OpenAI Responses API uses max_output_tokens. In the README table we also call
    # this `max_tokens`, because that wording is used in the homework.
    default_max_output_tokens: int = _get_int("DEFAULT_MAX_OUTPUT_TOKENS", 1200)
    openai_timeout_seconds: float = _get_float("OPENAI_TIMEOUT_SECONDS", 45.0)

    # Context is intentionally in RAM for this assignment.
    context_max_messages: int = _get_int("CONTEXT_MAX_MESSAGES", 12)
    max_user_message_chars: int = _get_int("MAX_USER_MESSAGE_CHARS", 3000)
    max_assistant_context_chars: int = _get_int("MAX_ASSISTANT_CONTEXT_CHARS", 1800)

    # Telegram has a 4096 character message limit. We keep a safety margin.
    telegram_chunk_size: int = _get_int("TELEGRAM_CHUNK_SIZE", 3800)

    # Cost estimate is intentionally configurable because API prices change.
    # Defaults are conservative placeholders for older GPT-5 mini style pricing.
    # Update these values from the OpenAI pricing page before final submission.
    input_price_per_1m_tokens_usd: float = _get_float("INPUT_PRICE_PER_1M_TOKENS_USD", 0.25)
    output_price_per_1m_tokens_usd: float = _get_float("OUTPUT_PRICE_PER_1M_TOKENS_USD", 2.00)

    # Some future/reasoning models may ignore or reject optional parameters. The bot logs
    # this and retries without them so the demo does not fail during class.
    retry_without_temperature: bool = _get_bool("RETRY_WITHOUT_TEMPERATURE", True)
    retry_without_reasoning: bool = _get_bool("RETRY_WITHOUT_REASONING", True)

    # Logging.
    log_dir: Path = Path(os.getenv("LOG_DIR", str(PROJECT_ROOT / "logs")))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    hash_user_ids_in_logs: bool = _get_bool("HASH_USER_IDS_IN_LOGS", True)
    log_salt: str = os.getenv("LOG_SALT", "dev-salt-change-me")

    def validate(self) -> None:
        missing = []
        if not self.bot_token:
            missing.append("BOT_TOKEN")
        if not self.openai_api_key:
            missing.append("OPENAI_API_KEY")
        if missing:
            names = ", ".join(missing)
            raise RuntimeError(
                f"Missing required environment variables: {names}. "
                "Create .env from .env.example and fill in your keys."
            )


settings = Settings()
