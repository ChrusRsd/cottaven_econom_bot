"""Formatting and parsing helpers."""

from __future__ import annotations

import html
import shlex
from datetime import datetime
from typing import Iterable

from aiogram.types import TelegramObject


CURRENCY_LABELS = {
    "usd": "USD",
}


def user_link(user: dict) -> str:
    """Create a no-ping HTML link to a Telegram profile."""

    label = html.escape(user["full_name"])
    return f'<a href="tg://user?id={user["telegram_id"]}">{label}</a>'


def format_money(amount: int, currency: str) -> str:
    """Format an integer amount with a currency marker."""

    label = CURRENCY_LABELS.get(currency.lower(), currency.upper())
    return f"{amount:,} {label}".replace(",", " ")


def format_role(role: str) -> str:
    labels = {
        "citizen": "Житель штата",
        "admin": "Администратор",
        "president": "Президент",
        "owner": "Владелец",
    }
    return labels.get(role, role)


def parse_command_args(text: str | None) -> list[str]:
    """Split command text into arguments while supporting quotes."""

    if not text:
        return []
    chunks = text.strip().split(maxsplit=1)
    if len(chunks) < 2:
        return []
    try:
        return shlex.split(chunks[1])
    except ValueError:
        return chunks[1].split()


def normalize_currency(raw: str | None, default: str = "usd") -> str:
    """Map aliases to the single supported currency."""

    if not raw:
        return default
    cleaned = raw.strip().lower().replace("$", "usd")
    aliases = {
        "usd": "usd",
        "dollar": "usd",
        "dollars": "usd",
        "доллар": "usd",
        "доллары": "usd",
    }
    if cleaned not in aliases:
        raise ValueError("Бот работает только с валютой USD.")
    return aliases[cleaned]


def parse_positive_int(raw: str) -> int:
    """Parse a positive integer from free-form text."""

    cleaned = raw.replace(" ", "").replace(",", "")
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    if not cleaned.isdigit():
        raise ValueError("Нужно указать положительное целое число.")
    value = int(cleaned)
    if value <= 0:
        raise ValueError("Число должно быть больше нуля.")
    return value


def format_elapsed(moment: datetime, now: datetime) -> str:
    """Human-readable elapsed time."""

    delta = now - moment
    seconds = max(int(delta.total_seconds()), 0)
    days, seconds = divmod(seconds, 86_400)
    hours, seconds = divmod(seconds, 3_600)
    minutes, _ = divmod(seconds, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} дн.")
    if hours:
        parts.append(f"{hours} ч.")
    if minutes and len(parts) < 2:
        parts.append(f"{minutes} мин.")
    if not parts:
        parts.append("меньше минуты")
    return " ".join(parts)


def clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def split_pipe_sections(payload: str, expected: int, example: str | None = None) -> list[str]:
    """Split text by | and return trimmed sections."""

    parts = [part.strip() for part in payload.split("|")]
    if len(parts) < expected or any(not part for part in parts[:expected]):
        if example:
            raise ValueError(f"Данные заполнены неправильно.\nПример: {example}")
        raise ValueError("Данные заполнены неправильно. Разделите части символом |.")
    return parts


def ensure_from_user(obj: TelegramObject):
    """Return obj.from_user if present."""

    from_user = getattr(obj, "from_user", None)
    if from_user is None:
        raise RuntimeError("Telegram did not provide from_user.")
    return from_user


def join_lines(lines: Iterable[str]) -> str:
    return "\n".join(line for line in lines if line is not None)
