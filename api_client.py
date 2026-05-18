"""OpenAI API client for Telegram Prompt Lab Bot.

Uses the modern Responses API. The code logs request parameters, response IDs,
usage tokens, response status and estimated cost for the homework report.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AsyncOpenAI,
    BadRequestError,
    RateLimitError,
)

from config import Settings, settings
from context_manager import UsageRecord


logger = logging.getLogger(__name__)


SYSTEM_INSTRUCTIONS = """Ты Telegram Prompt Lab Bot.
Отвечай на русском языке, если пользователь не просит другой язык.
Будь полезным, ясным и практичным.
Не выдумывай факты; если не уверен, прямо скажи об этом.

В обычном диалоге отвечай естественно и достаточно кратко.

В режимах сравнения:
- строго следуй стилю конкретного режима;
- не задавай пользователю встречных вопросов;
- не добавляй финальные фразы вроде «если хочешь, могу...»;
- не предлагай продолжение диалога;
- не растягивай ответ сверх указанного формата.

Если объясняешь Docker Compose:
- используй современную команду `docker compose`, например `docker compose up`;
- не используй legacy-вариант `docker-compose`, если только не объясняешь отличие старого и нового синтаксиса;
- название файла `docker-compose.yml` можно использовать, это нормально.
"""


@dataclass(frozen=True, slots=True)
class RunPreset:
    """A Prompt Lab generation mode."""

    mode: str
    label: str
    temperature: float | None
    reasoning_effort: str | None
    max_output_tokens: int
    effect: str
    extra_instruction: str


@dataclass(slots=True)
class ModelResult:
    text: str
    usage: UsageRecord


COMPARE_PRESETS: tuple[RunPreset, ...] = (
    RunPreset(
        mode="compact",
        label="Compact",
        temperature=0.2,
        reasoning_effort="minimal",
        max_output_tokens=800,
        effect="сжатость через инструкцию, минимум воды",
        extra_instruction=(
            "Дай очень краткий ответ: максимум 4-5 предложений. "
            "Не используй длинные списки. "
            "Не добавляй вступление, вывод отдельным блоком и предложения продолжить. "
            "Главная цель — быстро объяснить суть."
        ),
    ),
    RunPreset(
        mode="balanced",
        label="Balanced",
        temperature=0.5,
        reasoning_effort="low",
        max_output_tokens=1100,
        effect="баланс ясности и полноты",
        extra_instruction=(
            "Дай структурированный ответ: короткое объяснение, 3-4 ключевых пункта "
            "и короткий практический вывод. "
            "Не добавляй предложения продолжить и не задавай вопросов пользователю. "
            "Ответ должен быть полезным, но не чрезмерно длинным."
        ),
    ),
    RunPreset(
        mode="creative",
        label="Creative",
        temperature=0.9,
        reasoning_effort="low",
        max_output_tokens=1000,
        effect="образный стиль без лишнего растягивания",
        extra_instruction=(
            "Объясни живо и образно, добавь ровно одну аналогию или один мини-пример. "
            "Максимум 10-12 предложений. "
            "Не добавляй длинные списки, блоки «Когда полезен», «Ограничения» и фразы "
            "вроде «если хочешь, могу...». "
            "Сохрани практическую пользу и умеренную длину."
        ),
    ),
)


DEFAULT_PRESET = RunPreset(
    mode="dialog",
    label="Dialog",
    temperature=0.5,
    reasoning_effort="low",
    max_output_tokens=settings.default_max_output_tokens,
    effect="обычный диалог с контекстом",
    extra_instruction=(
        "Ответь как полезный ассистент в Telegram. "
        "Держи ответ компактным. "
        "Не добавляй лишние предложения продолжить, если пользователь прямо этого не просит."
    ),
)


class OpenAIClient:
    """Small wrapper around AsyncOpenAI with logging and cost calculation."""

    def __init__(self, cfg: Settings = settings) -> None:
        self.cfg = cfg
        self.client = AsyncOpenAI(
            api_key=cfg.openai_api_key,
            timeout=cfg.openai_timeout_seconds,
        )
        self.usage_log_path = Path(cfg.log_dir) / "usage.jsonl"
        self.usage_log_path.parent.mkdir(parents=True, exist_ok=True)

    async def ask(
        self,
        *,
        user_id: int,
        prompt: str,
        context_messages: list[dict[str, str]],
        preset: RunPreset = DEFAULT_PRESET,
    ) -> ModelResult:
        """Send one request to OpenAI and return text + usage."""

        input_messages = self._build_input_messages(context_messages, prompt)
        instructions = f"{SYSTEM_INSTRUCTIONS}\n\nРежим ответа: {preset.label}. {preset.extra_instruction}"
        params: dict[str, Any] = {
            "model": self.cfg.openai_model,
            "instructions": instructions,
            "input": input_messages,
            "max_output_tokens": preset.max_output_tokens,
            "store": False,
        }
        if preset.temperature is not None:
            params["temperature"] = preset.temperature
        if preset.reasoning_effort is not None:
            params["reasoning"] = {"effort": preset.reasoning_effort}

        safe_user_id = self._safe_user_id(user_id)
        request_log = {
            "event": "openai_request",
            "user_id": safe_user_id,
            "mode": preset.mode,
            "model": self.cfg.openai_model,
            "temperature": preset.temperature,
            "reasoning_effort": preset.reasoning_effort,
            "max_output_tokens": preset.max_output_tokens,
            "context_messages": len(context_messages),
            "prompt_preview": prompt[:180],
        }
        logger.info("OpenAI request params: %s", json.dumps(request_log, ensure_ascii=False))

        response, warnings, actual_temperature, actual_reasoning_effort = await self._create_with_fallbacks(
            params=params,
            request_log=request_log,
            preset=preset,
        )

        text = self._extract_text(response)
        response_status = self._response_status(response)
        incomplete_reason = self._incomplete_reason(response)

        if response_status == "incomplete":
            if incomplete_reason == "max_output_tokens":
                warnings.append(
                    "ответ был обрезан по max_output_tokens; увеличьте лимит, если нужен полный ответ"
                )
            else:
                warnings.append(f"ответ завершился со статусом incomplete: {incomplete_reason or 'unknown'}")

        if not text:
            text = self._empty_text_placeholder(response_status, incomplete_reason)
            warnings.append("модель вернула ответ без видимого текста")

        usage_record = self._make_usage_record(
            response=response,
            preset=preset,
            actual_temperature=actual_temperature,
            actual_reasoning_effort=actual_reasoning_effort,
            response_status=response_status,
            incomplete_reason=incomplete_reason,
            warning="; ".join(dict.fromkeys(warnings)) if warnings else None,
        )
        self._append_usage_log(user_id=safe_user_id, record=usage_record)
        return ModelResult(text=text, usage=usage_record)

    async def compare(
        self,
        *,
        user_id: int,
        prompt: str,
        context_messages: list[dict[str, str]],
    ) -> list[ModelResult]:
        """Run the same prompt through all Prompt Lab presets."""

        tasks = [
            self.ask(
                user_id=user_id,
                prompt=prompt,
                context_messages=context_messages,
                preset=preset,
            )
            for preset in COMPARE_PRESETS
        ]
        return list(await asyncio.gather(*tasks))

    async def _create_with_fallbacks(
        self,
        *,
        params: dict[str, Any],
        request_log: dict[str, Any],
        preset: RunPreset,
    ) -> tuple[Any, list[str], float | None, str | None]:
        """Create a response and gracefully remove unsupported optional params.

        Some GPT/reasoning models reject custom temperature; some accounts/models may
        also reject the reasoning object. The homework still asks to compare
        temperature/max tokens, so we keep planned values in logs and show actual
        values separately.
        """

        warnings: list[str] = []
        actual_temperature = preset.temperature
        actual_reasoning_effort = preset.reasoning_effort
        last_error: BadRequestError | None = None

        for _attempt in range(4):
            try:
                response = await self.client.responses.create(**params)
                return response, warnings, actual_temperature, actual_reasoning_effort
            except BadRequestError as exc:
                last_error = exc
                error_text = str(exc).lower()

                if self.cfg.retry_without_temperature and "temperature" in error_text and "temperature" in params:
                    logger.warning("Temperature rejected by model. Retrying without temperature: %s", exc)
                    params.pop("temperature", None)
                    actual_temperature = None
                    warnings.append("temperature был отклонён моделью; запрос повторён без temperature")
                    continue

                if self.cfg.retry_without_reasoning and (
                    "reasoning" in error_text or "effort" in error_text
                ) and "reasoning" in params:
                    logger.warning("Reasoning effort rejected by model. Retrying without reasoning: %s", exc)
                    params.pop("reasoning", None)
                    actual_reasoning_effort = None
                    warnings.append("reasoning.effort был отклонён моделью; запрос повторён без reasoning")
                    continue

                self._log_error("bad_request", exc, request_log)
                raise
            except (RateLimitError, APITimeoutError, APIConnectionError, APIError) as exc:
                self._log_error("api_error", exc, request_log)
                raise
            except Exception as exc:  # noqa: BLE001 - we want robust bot logging
                self._log_error("unexpected_error", exc, request_log)
                raise

        # Should be unreachable, but keeps type checkers and runtime safe.
        if last_error is not None:
            self._log_error("bad_request", last_error, request_log)
            raise last_error
        raise RuntimeError("OpenAI response was not created")

    def _build_input_messages(
        self,
        context_messages: list[dict[str, str]],
        prompt: str,
    ) -> list[dict[str, str]]:
        # Responses API accepts input as a string or as message objects.
        # We use message objects to preserve the per-user context.
        messages = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in context_messages
            if msg.get("role") in {"user", "assistant"} and msg.get("content")
        ]
        messages.append({"role": "user", "content": prompt})
        return messages

    def _make_usage_record(
        self,
        *,
        response: Any,
        preset: RunPreset,
        actual_temperature: float | None,
        actual_reasoning_effort: str | None,
        response_status: str | None,
        incomplete_reason: str | None,
        warning: str | None,
    ) -> UsageRecord:
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or 0)
        estimated_cost = self.estimate_cost(input_tokens, output_tokens)
        return UsageRecord(
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            mode=preset.mode,
            model=self.cfg.openai_model,
            planned_temperature=preset.temperature,
            actual_temperature=actual_temperature,
            reasoning_effort=actual_reasoning_effort,
            max_output_tokens=preset.max_output_tokens,
            response_status=response_status,
            incomplete_reason=incomplete_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost,
            response_id=getattr(response, "id", None),
            warning=warning,
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens / 1_000_000 * self.cfg.input_price_per_1m_tokens_usd
            + output_tokens / 1_000_000 * self.cfg.output_price_per_1m_tokens_usd
        )

    def _extract_text(self, response: Any) -> str:
        text = getattr(response, "output_text", None)
        if text:
            return str(text).strip()

        # Fallback for SDK versions where output_text is not populated.
        chunks: list[str] = []
        for item in getattr(response, "output", []) or []:
            for content in self._get_value(item, "content") or []:
                content_type = self._get_value(content, "type")
                piece = self._get_value(content, "text")
                if piece and (content_type in {"output_text", "text", None}):
                    chunks.append(str(piece))
        return "\n".join(chunks).strip()

    @staticmethod
    def _get_value(obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    @staticmethod
    def _response_status(response: Any) -> str | None:
        status = getattr(response, "status", None)
        return str(status) if status else None

    @staticmethod
    def _incomplete_reason(response: Any) -> str | None:
        details = getattr(response, "incomplete_details", None)
        if not details:
            return None
        reason = getattr(details, "reason", None)
        if reason is None and isinstance(details, dict):
            reason = details.get("reason")
        return str(reason) if reason else None

    @staticmethod
    def _empty_text_placeholder(response_status: str | None, incomplete_reason: str | None) -> str:
        if response_status == "incomplete" and incomplete_reason == "max_output_tokens":
            return (
                "⚠️ Ответ модели не содержит видимого текста: лимит max_output_tokens был исчерпан "
                "до формирования финального ответа. Увеличьте лимит токенов или используйте более короткий запрос."
            )
        if response_status == "incomplete":
            return (
                "⚠️ Ответ модели не содержит видимого текста: запрос завершился со статусом "
                f"incomplete ({incomplete_reason or 'unknown'})."
            )
        return "⚠️ Модель вернула пустой видимый ответ. Подробности см. в logs/bot.log и logs/usage.jsonl."

    def _append_usage_log(self, *, user_id: str, record: UsageRecord) -> None:
        payload = asdict(record)
        payload["event"] = "openai_response"
        payload["user_id"] = user_id
        with self.usage_log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        logger.info("OpenAI usage: %s", json.dumps(payload, ensure_ascii=False))

    def _safe_user_id(self, user_id: int) -> str:
        if not self.cfg.hash_user_ids_in_logs:
            return str(user_id)
        raw = f"{self.cfg.log_salt}:{user_id}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    @staticmethod
    def _log_error(kind: str, exc: Exception, request_log: dict[str, Any]) -> None:
        logger.exception(
            "OpenAI %s. request=%s error=%s",
            kind,
            json.dumps(request_log, ensure_ascii=False),
            str(exc),
        )
