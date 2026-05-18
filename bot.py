"""Telegram Prompt Lab Bot.

Run:
    python bot.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from api_client import COMPARE_PRESETS, DEFAULT_PRESET, ModelResult, OpenAIClient
from config import settings
from context_manager import ContextManager, UsageRecord


router = Router()
context_manager = ContextManager(
    max_messages=settings.context_max_messages,
    max_assistant_chars=settings.max_assistant_context_chars,
)
openai_client: OpenAIClient | None = None


HELP_TEXT = """🤖 Telegram Prompt Lab Bot

Обычный диалог:
Просто напиши сообщение — бот ответит с учётом последних сообщений.

Команды:
/start — приветствие
/help — справка
/reset — очистить контекст и статистику
/stats — показать локальную статистику токенов
/compare <запрос> — яркая фича: сравнить 3 режима ответа модели

Также можно написать: очистить контекст

Пример:
/compare Объясни Docker Compose простыми словами
"""


def setup_logging() -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    log_file = Path(settings.log_dir) / "bot.log"

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


def _require_client() -> OpenAIClient:
    if openai_client is None:
        raise RuntimeError("OpenAI client is not initialized")
    return openai_client


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Я Prompt Lab Bot: умею вести диалог с контекстом и сравнивать "
        "режимы генерации через /compare.\n\n" + HELP_TEXT
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    user_id = _user_id(message)
    context_manager.reset(user_id)
    await message.answer("✅ Контекст и локальная статистика очищены.")


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    user_id = _user_id(message)
    summary = context_manager.usage_summary(user_id)
    if summary["requests"] == 0:
        await message.answer("Пока нет статистики. Сделай обычный запрос или /compare.")
        return

    lines = [
        "📊 Локальная статистика текущего запуска",
        "",
        f"Запросов: {summary['requests']}",
        f"Input tokens: {summary['input_tokens']}",
        f"Output tokens: {summary['output_tokens']}",
        f"Total tokens: {summary['total_tokens']}",
        f"Ориентировочная стоимость: ${summary['estimated_cost_usd']:.6f}",
        "",
        "Последние прогоны:",
    ]
    for index, record in enumerate(summary["last_records"], start=1):
        lines.append(_format_usage_line(index, record))
    await message.answer("\n".join(lines))


@router.message(Command("compare"))
async def cmd_compare(message: Message) -> None:
    user_id = _user_id(message)
    prompt = _command_argument(message.text or "", "/compare")
    if not prompt:
        await message.answer(
            "Напиши запрос после команды.\n\n"
            "Пример:\n/compare Объясни Docker Compose простыми словами"
        )
        return

    prompt = _clip_user_text(prompt)
    await message.answer("🧪 Запускаю Prompt Lab: compact / balanced / creative...")

    client = _require_client()
    context_messages = context_manager.get_messages(user_id)
    try:
        results = await client.compare(
            user_id=user_id,
            prompt=prompt,
            context_messages=context_messages,
        )
    except Exception:  # noqa: BLE001 - error is logged inside api_client too
        logging.exception("/compare failed")
        await message.answer(
            "⚠️ Не удалось выполнить /compare. Проверь OPENAI_API_KEY, модель, баланс и логи в logs/bot.log."
        )
        return

    for result in results:
        context_manager.add_usage(user_id, result.usage)

    response_text = _format_compare_response(results)
    await send_long_message(message, response_text)

    # Keep context useful but do not store all three long answers.
    context_manager.append_pair(
        user_id,
        f"/compare {prompt}",
        _make_compare_context_summary(results),
    )


@router.message(F.text.casefold() == "очистить контекст")
async def text_reset(message: Message) -> None:
    await cmd_reset(message)


@router.message(F.text)
async def handle_text(message: Message) -> None:
    user_id = _user_id(message)
    user_text = _clip_user_text(message.text or "")
    client = _require_client()

    try:
        result = await client.ask(
            user_id=user_id,
            prompt=user_text,
            context_messages=context_manager.get_messages(user_id),
            preset=DEFAULT_PRESET,
        )
    except Exception:  # noqa: BLE001
        logging.exception("Dialog request failed")
        await message.answer(
            "⚠️ Не удалось получить ответ. Проверь ключи, модель, баланс и logs/bot.log."
        )
        return

    context_manager.add_usage(user_id, result.usage)
    context_manager.append_pair(user_id, user_text, result.text)
    await send_long_message(message, result.text)


async def send_long_message(message: Message, text: str) -> None:
    """Send text in Telegram-safe chunks, trying not to break paragraphs."""
    chunk_size = settings.telegram_chunk_size
    text = text.strip()

    if len(text) <= chunk_size:
        await message.answer(text)
        return

    chunks: list[str] = []
    current = ""

    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        candidate = f"{current}\n\n{paragraph}" if current else paragraph

        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(paragraph) <= chunk_size:
            current = paragraph
            continue

        # Fallback for very long paragraphs: split by lines first.
        for line in paragraph.splitlines():
            line = line.strip()
            if not line:
                continue

            candidate = f"{current}\n{line}" if current else line

            if len(candidate) <= chunk_size:
                current = candidate
                continue

            if current:
                chunks.append(current)
                current = ""

            # Last fallback: hard split a single very long line.
            while len(line) > chunk_size:
                chunks.append(line[:chunk_size])
                line = line[chunk_size:]

            current = line

    if current:
        chunks.append(current)

    for chunk in chunks:
        await message.answer(chunk)


def _format_compare_response(results: list[ModelResult]) -> str:
    by_mode = {result.usage.mode: result for result in results}
    lines: list[str] = [
        "🧪 Prompt Lab: сравнение режимов",
        "",
    ]

    for preset in COMPARE_PRESETS:
        result = by_mode[preset.mode]
        lines.extend(
            [
                f"=== {preset.label} ===",
                result.text,
            ]
        )
        if result.usage.incomplete_reason:
            lines.append(
                f"⚠️ Диагностика: response_status={result.usage.response_status}, "
                f"reason={result.usage.incomplete_reason}"
            )
        lines.append("")

    lines.extend(
        [
            "📊 Параметры и usage",
            "№ | режим | temp план/факт | effort | max_tokens | статус | эффект | tokens | cost | response_id",
        ]
    )
    for index, preset in enumerate(COMPARE_PRESETS, start=1):
        record = by_mode[preset.mode].usage
        planned = _fmt_temp(record.planned_temperature)
        actual = _fmt_temp(record.actual_temperature)
        effort = _fmt_effort(record.reasoning_effort)
        status = record.response_status or "—"
        response_id = _short_response_id(record.response_id)
        lines.append(
            f"{index} | {record.mode} | {planned}/{actual} | {effort} | "
            f"{record.max_output_tokens} | {status} | {preset.effect} | "
            f"{record.total_tokens} | ${record.estimated_cost_usd:.6f} | {response_id}"
        )
        if record.warning:
            lines.append(f"  ⚠️ {record.warning}")
    lines.append(
        "\nПолные записи usage сохраняются в logs/usage.jsonl. "
        "Если temp/effort отклонены моделью, бот показывает плановое и фактическое значение отдельно."
    )
    return "\n".join(lines)


def _make_compare_context_summary(results: list[ModelResult]) -> str:
    summary_lines = ["Показаны 3 режима Prompt Lab:"]
    for result in results:
        first_line = result.text.splitlines()[0] if result.text else ""
        summary_lines.append(f"- {result.usage.mode}: {first_line[:220]}")
    return "\n".join(summary_lines)


def _format_usage_line(index: int, record: UsageRecord) -> str:
    response_id = _short_response_id(record.response_id)
    status = record.response_status or "—"
    return (
        f"{index}. {record.mode} | temp {_fmt_temp(record.planned_temperature)}/"
        f"{_fmt_temp(record.actual_temperature)} | effort {_fmt_effort(record.reasoning_effort)} | "
        f"max {record.max_output_tokens} | status {status} | "
        f"tokens {record.total_tokens} | ${record.estimated_cost_usd:.6f} | {response_id}"
    )


def _fmt_temp(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}"


def _fmt_effort(value: str | None) -> str:
    return value or "—"


def _short_response_id(response_id: str | None) -> str:
    if not response_id:
        return "—"
    if len(response_id) <= 18:
        return response_id
    return response_id[:14] + "…"


def _command_argument(text: str, command: str) -> str:
    # Handles `/compare text` and `/compare@BotName text`.
    first, _, rest = text.partition(" ")
    if first.startswith(command):
        return rest.strip()
    return ""


def _clip_user_text(text: str) -> str:
    text = text.strip()
    if len(text) <= settings.max_user_message_chars:
        return text
    return text[: settings.max_user_message_chars].rstrip() + "\n...[message clipped]"


def _user_id(message: Message) -> int:
    if message.from_user is None:
        # Rare but keeps type checkers and runtime safe.
        return 0
    return int(message.from_user.id)


async def main() -> None:
    global openai_client
    setup_logging()
    settings.validate()
    openai_client = OpenAIClient(settings)

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    dp.include_router(router)

    logging.info("Starting Telegram Prompt Lab Bot with model=%s", settings.openai_model)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
