"""SQLite helpers for the Montana economy bot."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

from bot.config import Settings


logger = logging.getLogger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'citizen',
    is_government INTEGER NOT NULL DEFAULT 0,
    usd_balance INTEGER NOT NULL DEFAULT 0,
    car_fuel INTEGER NOT NULL DEFAULT 40,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL COLLATE NOCASE,
    quantity INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, name),
    FOREIGN KEY (user_id) REFERENCES users(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL,
    recipient_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    accepted_at TEXT,
    FOREIGN KEY (sender_id) REFERENCES users(telegram_id) ON DELETE CASCADE,
    FOREIGN KEY (recipient_id) REFERENCES users(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS taxes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount_usd INTEGER NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (created_by) REFERENCES users(telegram_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS fines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id INTEGER NOT NULL,
    issuer_id INTEGER,
    amount_usd INTEGER NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    issued_at TEXT NOT NULL,
    due_at TEXT NOT NULL,
    paid_at TEXT,
    removed_at TEXT,
    auto_wanted_created INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (target_id) REFERENCES users(telegram_id) ON DELETE CASCADE,
    FOREIGN KEY (issuer_id) REFERENCES users(telegram_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS wanteds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id INTEGER NOT NULL,
    full_name_text TEXT NOT NULL,
    appearance TEXT NOT NULL,
    reason TEXT NOT NULL,
    issuer_id INTEGER,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    removed_at TEXT,
    removed_by INTEGER,
    system_generated INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (target_id) REFERENCES users(telegram_id) ON DELETE CASCADE,
    FOREIGN KEY (issuer_id) REFERENCES users(telegram_id) ON DELETE SET NULL,
    FOREIGN KEY (removed_by) REFERENCES users(telegram_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS wanted_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name_text TEXT NOT NULL,
    appearance TEXT NOT NULL,
    reason TEXT NOT NULL,
    issuer_id INTEGER,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    removed_at TEXT,
    removed_by INTEGER,
    system_generated INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (issuer_id) REFERENCES users(telegram_id) ON DELETE SET NULL,
    FOREIGN KEY (removed_by) REFERENCES users(telegram_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER,
    source_kind TEXT NOT NULL,
    source_id INTEGER,
    target_kind TEXT NOT NULL,
    target_id INTEGER,
    currency TEXT NOT NULL,
    amount INTEGER NOT NULL,
    kind TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_targets (
    kind TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    thread_id INTEGER NOT NULL,
    created_by INTEGER,
    created_at TEXT NOT NULL,
    PRIMARY KEY (kind, chat_id, thread_id),
    FOREIGN KEY (created_by) REFERENCES users(telegram_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS market_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    post_kind TEXT NOT NULL,
    category_tag TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    item_name TEXT,
    quantity INTEGER NOT NULL DEFAULT 0,
    remaining_quantity INTEGER NOT NULL DEFAULT 0,
    price_usd INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    closed_at TEXT,
    FOREIGN KEY (owner_id) REFERENCES users(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS special_access (
    user_id INTEGER PRIMARY KEY,
    mega_access INTEGER NOT NULL DEFAULT 0,
    conglomerate_access INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    org_type TEXT NOT NULL,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    direction TEXT NOT NULL,
    short_description TEXT NOT NULL,
    capital_usd INTEGER NOT NULL DEFAULT 0,
    payroll_usd INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    deleted_at TEXT,
    FOREIGN KEY (owner_id) REFERENCES users(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS organization_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    name TEXT NOT NULL COLLATE NOCASE,
    created_at TEXT NOT NULL,
    UNIQUE(organization_id, name),
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS organization_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    member_type TEXT NOT NULL DEFAULT 'staff',
    role_id INTEGER,
    joined_at TEXT NOT NULL,
    UNIQUE(organization_id, user_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(telegram_id) ON DELETE CASCADE,
    FOREIGN KEY (role_id) REFERENCES organization_roles(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS organization_invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    invited_by INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    responded_at TEXT,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(telegram_id) ON DELETE CASCADE,
    FOREIGN KEY (invited_by) REFERENCES users(telegram_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_government ON users(is_government);
CREATE INDEX IF NOT EXISTS idx_checks_recipient ON checks(recipient_id, status);
CREATE INDEX IF NOT EXISTS idx_fines_target ON fines(target_id, status);
CREATE INDEX IF NOT EXISTS idx_fines_due ON fines(status, due_at);
CREATE INDEX IF NOT EXISTS idx_wanteds_target ON wanteds(target_id, status);
CREATE INDEX IF NOT EXISTS idx_wanted_cases_status ON wanted_cases(status, created_at);
CREATE INDEX IF NOT EXISTS idx_transactions_kind ON transactions(kind, created_at);
CREATE INDEX IF NOT EXISTS idx_notification_targets_kind ON notification_targets(kind, created_at);
CREATE INDEX IF NOT EXISTS idx_market_posts_status ON market_posts(status, created_at);
CREATE INDEX IF NOT EXISTS idx_market_posts_owner ON market_posts(owner_id, status);
CREATE INDEX IF NOT EXISTS idx_organizations_owner ON organizations(owner_id, status);
CREATE INDEX IF NOT EXISTS idx_organizations_type ON organizations(org_type, status);
CREATE INDEX IF NOT EXISTS idx_organization_members_org ON organization_members(organization_id, member_type);
CREATE INDEX IF NOT EXISTS idx_organization_members_user ON organization_members(user_id);
CREATE INDEX IF NOT EXISTS idx_organization_invites_user ON organization_invites(user_id, status);
"""


class Database:
    """Thin async wrapper around aiosqlite."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = settings.db_path
        self.connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the SQLite connection."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(str(self.path), timeout=30)
        self.connection.row_factory = aiosqlite.Row
        await self.connection.execute("PRAGMA foreign_keys = ON")
        await self.connection.execute("PRAGMA busy_timeout = 5000")
        await self.connection.execute("PRAGMA temp_store = MEMORY")
        try:
            await self.connection.execute("PRAGMA journal_mode = WAL")
            await self.connection.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.OperationalError as exc:
            logger.warning(
                "SQLite WAL mode is unavailable for %s, continuing with the default journal mode: %s",
                self.path,
                exc,
            )
            try:
                await self.connection.execute("PRAGMA synchronous = FULL")
            except sqlite3.OperationalError as sync_exc:
                logger.warning(
                    "SQLite synchronous pragma is unavailable for %s, continuing without journal tuning: %s",
                    self.path,
                    sync_exc,
                )
        await self.connection.executescript(SCHEMA)
        await self.connection.commit()
        await self._ensure_meta_defaults()

    async def close(self) -> None:
        """Close the current database connection."""

        if self.connection is not None:
            await self.connection.close()
            self.connection = None

    def _conn(self) -> aiosqlite.Connection:
        if self.connection is None:
            raise RuntimeError("Database is not connected.")
        return self.connection

    async def _ensure_meta_defaults(self) -> None:
        defaults = {
            "treasury_usd": str(self.settings.initial_treasury_usd),
            "gov_salary_usd": str(self.settings.default_gov_salary_usd),
            "fine_chat_id": "",
            "fine_thread_id": "",
            "wanted_chat_id": "",
            "wanted_thread_id": "",
            "last_weekly_tax_run": "",
            "last_business_income_run": "",
            "last_company_income_run": "",
            "last_super_income_run": "",
            "last_salary_slot_0": "",
            "last_salary_slot_1": "",
            "last_fine_scan_hour": "",
        }
        for key, value in defaults.items():
            await self._conn().execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES(?, ?)",
                (key, value),
            )
        await self._conn().commit()

    async def execute(self, query: str, params: tuple[Any, ...] = ()) -> aiosqlite.Cursor:
        return await self._conn().execute(query, params)

    async def executescript(self, script: str) -> None:
        await self._conn().executescript(script)

    async def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> aiosqlite.Row | None:
        cursor = await self._conn().execute(query, params)
        return await cursor.fetchone()

    async def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        cursor = await self._conn().execute(query, params)
        return await cursor.fetchall()

    async def fetchval(self, query: str, params: tuple[Any, ...] = ()) -> Any:
        row = await self.fetchone(query, params)
        if row is None:
            return None
        return row[0]

    async def commit(self) -> None:
        await self._conn().commit()

    async def rollback(self) -> None:
        await self._conn().rollback()

    @asynccontextmanager
    async def transaction(self):
        """Run a write transaction."""

        conn = self._conn()
        await conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            await conn.rollback()
            raise
        else:
            await conn.commit()
