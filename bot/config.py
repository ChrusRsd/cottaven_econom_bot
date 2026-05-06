"""Runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]


def _parse_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    return int(value.strip())


def _parse_int_tuple(value: str | None, default: tuple[int, ...]) -> tuple[int, ...]:
    if value is None or not value.strip():
        return default
    return tuple(int(chunk.strip()) for chunk in value.split(",") if chunk.strip())


def _parse_int_set(value: str | None, default: frozenset[int]) -> frozenset[int]:
    if value is None or not value.strip():
        return default
    return frozenset(int(chunk.strip()) for chunk in value.split(",") if chunk.strip())


@dataclass(slots=True, frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    bot_token: str
    db_path: Path
    timezone_name: str
    owner_ids: frozenset[int]
    primary_owner_id: int
    state_name: str
    initial_user_usd: int
    initial_treasury_usd: int
    weekly_tax_hour: int
    weekly_tax_minute: int
    salary_hours: tuple[int, ...]
    salary_minute: int
    fine_deadline_days: int
    default_gov_salary_usd: int

    @property
    def timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    """Load .env and create immutable settings."""

    load_dotenv(BASE_DIR / ".env")

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not configured.")

    default_owner_ids = frozenset({8376083253})
    owner_ids = _parse_int_set(os.getenv("OWNER_IDS"), default_owner_ids) | default_owner_ids
    db_path = Path(os.getenv("DB_PATH", "storage/montana_economy.sqlite3").strip())
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path

    return Settings(
        bot_token=token,
        db_path=db_path,
        timezone_name=os.getenv("TIMEZONE", "Europe/Moscow").strip(),
        owner_ids=owner_ids,
        primary_owner_id=8376083253,
        state_name=os.getenv("STATE_NAME", "Montana").strip() or "Montana",
        initial_user_usd=_parse_int(os.getenv("INITIAL_USER_USD"), 200),
        initial_treasury_usd=_parse_int(os.getenv("INITIAL_TREASURY_USD"), 10_000_000),
        weekly_tax_hour=_parse_int(os.getenv("WEEKLY_TAX_HOUR"), 18),
        weekly_tax_minute=_parse_int(os.getenv("WEEKLY_TAX_MINUTE"), 0),
        salary_hours=_parse_int_tuple(os.getenv("SALARY_HOURS"), (9, 21)),
        salary_minute=_parse_int(os.getenv("SALARY_MINUTE"), 0),
        fine_deadline_days=_parse_int(os.getenv("FINE_DEADLINE_DAYS"), 10),
        default_gov_salary_usd=_parse_int(os.getenv("DEFAULT_GOV_SALARY_USD"), 350),
    )
