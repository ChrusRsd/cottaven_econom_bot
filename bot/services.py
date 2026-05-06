"""Core business logic for the Montana economy bot."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import User as TelegramUser
from aiosqlite import Connection, Row

from bot.config import Settings
from bot.database import Database
from bot.utils import clamp, format_money, normalize_currency, user_link


PAGE_SIZE = 5

BUSINESS_DIRECTIONS = {
    "магазин",
    "кафе",
    "ферма",
    "автосервис",
    "юридические услуги",
    "логистика",
    "строительство",
    "такси",
    "азс",
    "охрана",
    "медицина",
    "бар",
    "ресторан",
    "отель",
    "мойка",
    "салон красоты",
    "доставка еды",
    "маркетинг",
    "ивент агентство",
    "ночной клуб",
    "стриптиз клуб",
    "ломбард",
    "ремонт техники",
    "образовательный центр",
    "агентство недвижимости",
}

BUSINESS_DIRECTION_ALIASES = {
    "сто": "автосервис",
    "сто": "автосервис",
    "стрипклуб": "стриптиз клуб",
    "стрип клуб": "стриптиз клуб",
    "стриптиз клубы": "стриптиз клуб",
    "стриптиз-клуб": "стриптиз клуб",
    "стриптиз-клубы": "стриптиз клуб",
    "ночные клубы": "ночной клуб",
    "ночной клубы": "ночной клуб",
    "азс station": "азс",
    "event агентство": "ивент агентство",
    "event agency": "ивент агентство",
}

ORG_CONFIG: dict[str, dict[str, Any]] = {
    "business": {
        "label": "Бизнес",
        "registration_fee": 150_000,
        "capital_refund_percent": 50,
        "custom_role_limit": 3,
        "requires_access": False,
        "fixed_direction_list": True,
    },
    "company": {
        "label": "Компания",
        "registration_fee": 2_000_000,
        "capital_refund_percent": 70,
        "custom_role_limit": 10,
        "requires_access": False,
        "fixed_direction_list": False,
    },
    "megacorp": {
        "label": "Мега-корпорация",
        "registration_fee": 0,
        "capital_refund_percent": 100,
        "custom_role_limit": None,
        "requires_access": "mega",
        "fixed_direction_list": False,
    },
    "conglomerate": {
        "label": "Глобальный конгломерат",
        "registration_fee": 0,
        "capital_refund_percent": 100,
        "custom_role_limit": None,
        "requires_access": "conglomerate",
        "fixed_direction_list": False,
    },
}


class ServiceError(RuntimeError):
    """User-facing application error."""


@dataclass(slots=True)
class Page:
    """Simple paginated result."""

    items: list[dict[str, Any]]
    page: int
    total_pages: int


class EconomyService:
    """Owns all mutable game mechanics."""

    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.db = database
        self._write_lock = asyncio.Lock()

    def now(self) -> datetime:
        return datetime.now(self.settings.timezone)

    def now_iso(self) -> str:
        return self.now().isoformat(timespec="seconds")

    async def _fetchone(self, conn: Connection, query: str, params: tuple[Any, ...] = ()) -> Row | None:
        cursor = await conn.execute(query, params)
        return await cursor.fetchone()

    async def _fetchall(self, conn: Connection, query: str, params: tuple[Any, ...] = ()) -> list[Row]:
        cursor = await conn.execute(query, params)
        return await cursor.fetchall()

    async def _fetchval(self, conn: Connection, query: str, params: tuple[Any, ...] = ()) -> Any:
        row = await self._fetchone(conn, query, params)
        if row is None:
            return None
        return row[0]

    def _user_from_row(self, row: Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def _balance_column(self, currency: str) -> str:
        normalize_currency(currency)
        return "usd_balance"

    async def _get_meta_conn(self, conn: Connection, key: str, default: str = "") -> str:
        row = await self._fetchone(conn, "SELECT value FROM meta WHERE key = ?", (key,))
        return default if row is None else str(row["value"])

    async def get_meta(self, key: str, default: str = "") -> str:
        row = await self.db.fetchone("SELECT value FROM meta WHERE key = ?", (key,))
        return default if row is None else str(row["value"])

    async def set_meta(self, key: str, value: str) -> None:
        async with self._write_lock:
            async with self.db.transaction() as conn:
                await conn.execute(
                    """
                    INSERT INTO meta(key, value) VALUES(?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, value),
                )

    async def _set_meta_conn(self, conn: Connection, key: str, value: str) -> None:
        await conn.execute(
            """
            INSERT INTO meta(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    async def _change_treasury_conn(self, conn: Connection, delta: int) -> int:
        current = int(await self._get_meta_conn(conn, "treasury_usd", "0"))
        updated = current + delta
        if updated < 0:
            raise ServiceError("В казне штата сейчас недостаточно средств.")
        await self._set_meta_conn(conn, "treasury_usd", str(updated))
        return updated

    async def get_treasury_usd(self) -> int:
        return int(await self.get_meta("treasury_usd", "0"))

    async def ensure_user(
        self,
        telegram_user: TelegramUser | None = None,
        *,
        telegram_id: int | None = None,
        username: str | None = None,
        full_name: str | None = None,
    ) -> dict[str, Any]:
        """Create or update a player record."""

        if telegram_user is not None:
            telegram_id = telegram_user.id
            username = telegram_user.username
            full_name = telegram_user.full_name or telegram_user.first_name or f"Игрок {telegram_user.id}"
        if telegram_id is None:
            raise ServiceError("Не удалось определить пользователя.")

        full_name = (full_name or f"Игрок {telegram_id}").strip()
        now_text = self.now_iso()
        role = "owner" if telegram_id in self.settings.owner_ids else "citizen"

        async with self._write_lock:
            async with self.db.transaction() as conn:
                current = await self._fetchone(
                    conn,
                    "SELECT * FROM users WHERE telegram_id = ?",
                    (telegram_id,),
                )
                if current is None:
                    await conn.execute(
                        """
                        INSERT INTO users(
                            telegram_id, username, full_name, role, is_government,
                            usd_balance, car_fuel, created_at, updated_at
                        )
                        VALUES(?, ?, ?, ?, 0, ?, 40, ?, ?)
                        """,
                        (
                            telegram_id,
                            username,
                            full_name,
                            role,
                            self.settings.initial_user_usd,
                            now_text,
                            now_text,
                        ),
                    )
                else:
                    current_role = current["role"]
                    next_role = "owner" if telegram_id in self.settings.owner_ids else current_role
                    await conn.execute(
                        """
                        UPDATE users
                        SET username = ?, full_name = ?, role = ?, updated_at = ?
                        WHERE telegram_id = ?
                        """,
                        (username, full_name, next_role, now_text, telegram_id),
                    )
        user = await self.get_user(telegram_id)
        if user is None:
            raise ServiceError("Не удалось подготовить профиль пользователя.")
        return user

    async def get_user(self, telegram_id: int) -> dict[str, Any] | None:
        row = await self.db.fetchone("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        return self._user_from_row(row)

    async def resolve_reference(
        self,
        reference: str | None = None,
        *,
        reply_user: TelegramUser | None = None,
    ) -> dict[str, Any]:
        """Resolve @username, numeric ID, or reply target."""

        if reply_user is not None:
            return await self.ensure_user(reply_user)

        if not reference:
            raise ServiceError("Нужно указать пользователя через reply, ID или @username.")

        cleaned = reference.strip()
        if cleaned.isdigit():
            user = await self.get_user(int(cleaned))
            if user is not None:
                return user
            raise ServiceError("Пользователь с таким ID ещё не попадал в базу бота.")

        username = cleaned[1:] if cleaned.startswith("@") else cleaned
        row = await self.db.fetchone(
            "SELECT * FROM users WHERE lower(username) = lower(?)",
            (username,),
        )
        if row is None:
            raise ServiceError("Пользователь с таким username ещё не попадал в базу бота.")
        return dict(row)

    async def list_active_taxes(self) -> list[int]:
        rows = await self.db.fetchall(
            "SELECT amount_usd FROM taxes WHERE is_active = 1 ORDER BY id ASC"
        )
        return [int(row["amount_usd"]) for row in rows]

    async def set_taxes(self, actor: dict[str, Any], amounts: list[int]) -> list[int]:
        """Replace the full weekly tax configuration."""

        if actor["role"] not in {"president", "owner"}:
            raise ServiceError("Налоги может менять только президент или владелец.")
        if not amounts:
            raise ServiceError("Укажите хотя бы один налог.")
        if len(amounts) > 3:
            raise ServiceError("Президент может держать не больше трёх налогов одновременно.")
        if any(amount <= 0 for amount in amounts):
            raise ServiceError("Все налоги должны быть положительными.")
        if sum(amounts) > 700:
            raise ServiceError("Сумма всех налогов не может превышать 700 USD.")

        async with self._write_lock:
            async with self.db.transaction() as conn:
                await conn.execute("UPDATE taxes SET is_active = 0 WHERE is_active = 1")
                for amount in amounts:
                    await conn.execute(
                        """
                        INSERT INTO taxes(amount_usd, is_active, created_by, created_at)
                        VALUES(?, 1, ?, ?)
                        """,
                        (amount, actor["telegram_id"], self.now_iso()),
                    )
        return amounts

    async def get_balance_overview(self, user_id: int) -> dict[str, Any]:
        user = await self.get_user(user_id)
        if user is None:
            raise ServiceError("Профиль игрока не найден.")
        fine_count = int(
            await self.db.fetchval(
                """
                SELECT COUNT(*) FROM fines
                WHERE target_id = ? AND status IN ('active', 'overdue')
                """,
                (user_id,),
            )
            or 0
        )
        recent = await self.db.fetchall(
            """
            SELECT * FROM transactions
            WHERE (source_kind = 'user' AND source_id = ?)
               OR (target_kind = 'user' AND target_id = ?)
            ORDER BY id DESC
            LIMIT 5
            """,
            (user_id, user_id),
        )
        pending_invites = int(
            await self.db.fetchval(
                "SELECT COUNT(*) FROM organization_invites WHERE user_id = ? AND status = 'pending'",
                (user_id,),
            )
            or 0
        )
        organization = await self.get_user_organization(user_id)
        if organization is not None:
            organization["type_label"] = self._organization_config(str(organization["org_type"]))["label"]
        return {
            "user": user,
            "fine_count": fine_count,
            "recent": [dict(row) for row in recent],
            "pending_invites": pending_invites,
            "organization": organization,
        }

    async def list_transaction_history(self, user_id: int, page: int = 0) -> Page:
        page = max(page, 0)
        count = int(
            await self.db.fetchval(
                """
                SELECT COUNT(*)
                FROM transactions
                WHERE (source_kind = 'user' AND source_id = ?)
                   OR (target_kind = 'user' AND target_id = ?)
                """,
                (user_id, user_id),
            )
            or 0
        )
        total_pages = max((count + PAGE_SIZE - 1) // PAGE_SIZE, 1)
        page = min(page, total_pages - 1)
        rows = await self.db.fetchall(
            """
            SELECT * FROM transactions
            WHERE (source_kind = 'user' AND source_id = ?)
               OR (target_kind = 'user' AND target_id = ?)
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, user_id, PAGE_SIZE, page * PAGE_SIZE),
        )
        return Page(items=[dict(row) for row in rows], page=page, total_pages=total_pages)

    async def list_inventory(self, user_id: int) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            """
            SELECT name, quantity
            FROM items
            WHERE user_id = ? AND quantity > 0
            ORDER BY name COLLATE NOCASE ASC
            """,
            (user_id,),
        )
        return [dict(row) for row in rows]

    def _organization_config(self, org_type: str) -> dict[str, Any]:
        try:
            return ORG_CONFIG[org_type]
        except KeyError as exc:
            raise ServiceError("Неизвестный тип организации.") from exc

    def _normalize_direction_key(self, direction: str) -> str:
        return " ".join(
            direction.strip().lower().replace("ё", "е").replace("-", " ").split()
        )

    def _normalize_business_direction(self, org_type: str, direction: str) -> str:
        cleaned = direction.strip()
        if not cleaned:
            raise ServiceError("Нужно указать направление организации.")
        config = self._organization_config(org_type)
        if not config["fixed_direction_list"]:
            return cleaned
        normalized = self._normalize_direction_key(cleaned)
        normalized = BUSINESS_DIRECTION_ALIASES.get(normalized, normalized)
        for allowed in BUSINESS_DIRECTIONS:
            if normalized == self._normalize_direction_key(allowed):
                return allowed.title()
        options = ", ".join(sorted(item.title() for item in BUSINESS_DIRECTIONS))
        raise ServiceError(f"Для бизнеса доступно только фиксированное направление. Варианты: {options}.")

    def _organization_role_limit(self, org_type: str) -> int | None:
        return self._organization_config(org_type)["custom_role_limit"]

    def _organization_refund_percent(self, org_type: str) -> int:
        return int(self._organization_config(org_type)["capital_refund_percent"])

    async def get_user_organization(self, user_id: int) -> dict[str, Any] | None:
        row = await self.db.fetchone(
            """
            SELECT
                o.*,
                m.member_type,
                r.name AS custom_role_name
            FROM organization_members m
            JOIN organizations o ON o.id = m.organization_id
            LEFT JOIN organization_roles r ON r.id = m.role_id
            WHERE m.user_id = ? AND o.status = 'active'
            ORDER BY CASE WHEN m.member_type = 'owner' THEN 0 ELSE 1 END, o.id ASC
            LIMIT 1
            """,
            (user_id,),
        )
        return dict(row) if row is not None else None

    async def _get_organization_by_owner(self, owner_id: int, allowed_types: set[str] | None = None) -> dict[str, Any] | None:
        params: list[Any] = [owner_id]
        where = ["o.owner_id = ?", "o.status = 'active'"]
        if allowed_types:
            placeholders = ", ".join("?" for _ in allowed_types)
            where.append(f"o.org_type IN ({placeholders})")
            params.extend(sorted(allowed_types))
        row = await self.db.fetchone(
            f"""
            SELECT o.*
            FROM organizations o
            WHERE {' AND '.join(where)}
            ORDER BY o.id ASC
            LIMIT 1
            """,
            tuple(params),
        )
        return dict(row) if row is not None else None

    async def _get_organization_by_name(self, name: str) -> dict[str, Any] | None:
        row = await self.db.fetchone(
            """
            SELECT *
            FROM organizations
            WHERE status = 'active' AND name = ? COLLATE NOCASE
            LIMIT 1
            """,
            (name.strip(),),
        )
        return dict(row) if row is not None else None

    async def _get_organization_member_row(self, organization_id: int, user_id: int) -> dict[str, Any] | None:
        row = await self.db.fetchone(
            """
            SELECT m.*, r.name AS custom_role_name
            FROM organization_members m
            LEFT JOIN organization_roles r ON r.id = m.role_id
            WHERE m.organization_id = ? AND m.user_id = ?
            """,
            (organization_id, user_id),
        )
        return dict(row) if row is not None else None

    async def _require_owned_organization(self, actor: dict[str, Any], allowed_types: set[str]) -> dict[str, Any]:
        organization = await self._get_organization_by_owner(actor["telegram_id"], allowed_types)
        if organization is None:
            labels = ", ".join(self._organization_config(kind)["label"] for kind in sorted(allowed_types))
            raise ServiceError(f"У вас нет активной организации этого типа. Нужна регистрация: {labels}.")
        return organization

    async def list_notification_targets(self, kind: str) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            """
            SELECT kind, chat_id, thread_id, created_by, created_at
            FROM notification_targets
            WHERE kind = ?
            ORDER BY created_at ASC
            """,
            (kind,),
        )
        return [dict(row) for row in rows]

    async def set_topic_chat(self, actor: dict[str, Any], kind: str, chat_id: int, thread_id: int | None) -> None:
        self._ensure_admin(actor)
        if kind not in {"fine", "wanted", "vak"}:
            raise ServiceError("Неизвестный тип канала уведомлений.")
        if thread_id is None:
            raise ServiceError("Эта команда работает только внутри топика супергруппы.")
        async with self._write_lock:
            async with self.db.transaction() as conn:
                await conn.execute(
                    """
                    INSERT OR IGNORE INTO notification_targets(kind, chat_id, thread_id, created_by, created_at)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (kind, chat_id, thread_id, actor["telegram_id"], self.now_iso()),
                )
                if kind in {"fine", "wanted"}:
                    await self._set_meta_conn(conn, f"{kind}_chat_id", str(chat_id))
                    await self._set_meta_conn(conn, f"{kind}_thread_id", str(thread_id))

    async def send_topic_notice(self, bot: Bot, kind: str, text: str) -> bool:
        targets = await self.list_notification_targets(kind)
        delivered = False
        for target in targets:
            try:
                await bot.send_message(
                    int(target["chat_id"]),
                    text,
                    message_thread_id=int(target["thread_id"]),
                )
                delivered = True
            except TelegramAPIError:
                continue
        if delivered:
            return True
        chat_id = await self.get_meta(f"{kind}_chat_id", "")
        thread_id = await self.get_meta(f"{kind}_thread_id", "")
        if not chat_id or not thread_id:
            return False
        try:
            await bot.send_message(int(chat_id), text, message_thread_id=int(thread_id))
            return True
        except TelegramAPIError:
            return False

    async def _change_balance_conn(
        self,
        conn: Connection,
        user_id: int,
        currency: str,
        delta: int,
    ) -> dict[str, Any]:
        column = self._balance_column(currency)
        user = await self._fetchone(conn, "SELECT * FROM users WHERE telegram_id = ?", (user_id,))
        if user is None:
            raise ServiceError("Игрок не найден.")
        current = int(user[column])
        updated = current + delta
        if updated < 0:
            raise ServiceError("Недостаточно средств для этой операции.")
        await conn.execute(
            f"UPDATE users SET {column} = ?, updated_at = ? WHERE telegram_id = ?",
            (updated, self.now_iso(), user_id),
        )
        refreshed = await self._fetchone(conn, "SELECT * FROM users WHERE telegram_id = ?", (user_id,))
        return dict(refreshed)

    async def _change_item_conn(
        self,
        conn: Connection,
        user_id: int,
        item_name: str,
        delta: int,
    ) -> None:
        normalized = item_name.strip()
        if not normalized:
            raise ServiceError("Название предмета не может быть пустым.")
        row = await self._fetchone(
            conn,
            "SELECT * FROM items WHERE user_id = ? AND name = ? COLLATE NOCASE",
            (user_id, normalized),
        )
        now_text = self.now_iso()
        if row is None:
            if delta < 0:
                raise ServiceError("У игрока нет такого предмета.")
            await conn.execute(
                """
                INSERT INTO items(user_id, name, quantity, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (user_id, normalized, delta, now_text, now_text),
            )
            return
        updated = int(row["quantity"]) + delta
        if updated < 0:
            raise ServiceError("Недостаточно предметов для передачи.")
        await conn.execute(
            """
            UPDATE items
            SET quantity = ?, updated_at = ?
            WHERE id = ?
            """,
            (updated, now_text, row["id"]),
        )

    async def _log_transaction_conn(
        self,
        conn: Connection,
        *,
        actor_id: int | None,
        source_kind: str,
        source_id: int | None,
        target_kind: str,
        target_id: int | None,
        currency: str,
        amount: int,
        kind: str,
        description: str,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO transactions(
                actor_id, source_kind, source_id, target_kind, target_id,
                currency, amount, kind, description, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                actor_id,
                source_kind,
                source_id,
                target_kind,
                target_id,
                currency,
                amount,
                kind,
                description,
                self.now_iso(),
            ),
        )

    async def pay(
        self,
        actor: dict[str, Any],
        target: dict[str, Any],
        amount: int,
        currency: str = "usd",
    ) -> None:
        currency = normalize_currency(currency)
        if actor["telegram_id"] == target["telegram_id"]:
            raise ServiceError("Нельзя переводить деньги самому себе.")
        if amount <= 0:
            raise ServiceError("Сумма должна быть больше нуля.")

        async with self._write_lock:
            async with self.db.transaction() as conn:
                await self._change_balance_conn(conn, actor["telegram_id"], currency, -amount)
                await self._change_balance_conn(conn, target["telegram_id"], currency, amount)
                await self._log_transaction_conn(
                    conn,
                    actor_id=actor["telegram_id"],
                    source_kind="user",
                    source_id=actor["telegram_id"],
                    target_kind="user",
                    target_id=target["telegram_id"],
                    currency=currency,
                    amount=amount,
                    kind="pay",
                    description=f"Перевод между игроками ({currency.upper()})",
                )

    async def create_check(
        self,
        actor: dict[str, Any],
        target: dict[str, Any],
        amount: int,
        currency: str,
        reason: str,
    ) -> int:
        currency = normalize_currency(currency)
        if amount <= 0:
            raise ServiceError("Сумма чека должна быть больше нуля.")
        if actor["telegram_id"] == target["telegram_id"]:
            raise ServiceError("Нельзя выписать чек самому себе.")
        reason = reason.strip() or "Без пояснения"

        async with self._write_lock:
            async with self.db.transaction() as conn:
                await self._change_balance_conn(conn, actor["telegram_id"], currency, -amount)
                cursor = await conn.execute(
                    """
                    INSERT INTO checks(sender_id, recipient_id, amount, currency, reason, status, created_at)
                    VALUES(?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        actor["telegram_id"],
                        target["telegram_id"],
                        amount,
                        currency,
                        reason,
                        self.now_iso(),
                    ),
                )
                check_id = cursor.lastrowid
                await self._log_transaction_conn(
                    conn,
                    actor_id=actor["telegram_id"],
                    source_kind="user",
                    source_id=actor["telegram_id"],
                    target_kind="escrow",
                    target_id=check_id,
                    currency=currency,
                    amount=amount,
                    kind="check_created",
                    description=f"Чек #{check_id}: {reason}",
                )
                return int(check_id)

    async def list_pending_checks_for_user(self, user_id: int) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            """
            SELECT c.*, u.full_name AS sender_name, u.telegram_id AS sender_telegram_id
            FROM checks c
            JOIN users u ON u.telegram_id = c.sender_id
            WHERE c.recipient_id = ? AND c.status = 'pending'
            ORDER BY c.id DESC
            """,
            (user_id,),
        )
        return [dict(row) for row in rows]

    async def accept_check(self, actor: dict[str, Any], check_id: int) -> dict[str, Any]:
        async with self._write_lock:
            async with self.db.transaction() as conn:
                check = await self._fetchone(
                    conn,
                    "SELECT * FROM checks WHERE id = ? AND status = 'pending'",
                    (check_id,),
                )
                if check is None:
                    raise ServiceError("Активный чек с таким номером не найден.")
                if int(check["recipient_id"]) != actor["telegram_id"]:
                    raise ServiceError("Этот чек выписан не на вас.")
                await self._change_balance_conn(conn, actor["telegram_id"], check["currency"], int(check["amount"]))
                await conn.execute(
                    """
                    UPDATE checks
                    SET status = 'accepted', accepted_at = ?
                    WHERE id = ?
                    """,
                    (self.now_iso(), check_id),
                )
                await self._log_transaction_conn(
                    conn,
                    actor_id=actor["telegram_id"],
                    source_kind="escrow",
                    source_id=check_id,
                    target_kind="user",
                    target_id=actor["telegram_id"],
                    currency=str(check["currency"]),
                    amount=int(check["amount"]),
                    kind="check_accepted",
                    description=f"Погашен чек #{check_id}",
                )
                return dict(check)

    async def get_top(self, currency: str, limit: int = 10) -> list[dict[str, Any]]:
        column = self._balance_column(currency)
        rows = await self.db.fetchall(
            f"""
            SELECT telegram_id, full_name, username, {column} AS balance
            FROM users
            ORDER BY {column} DESC, full_name ASC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in rows]

    async def get_stats(self) -> dict[str, Any]:
        total_users = int(await self.db.fetchval("SELECT COUNT(*) FROM users") or 0)
        total_usd = int(await self.db.fetchval("SELECT COALESCE(SUM(usd_balance), 0) FROM users") or 0)
        treasury_usd = await self.get_treasury_usd()
        richest = await self.get_top("usd", limit=1)
        return {
            "players": total_users,
            "usd_total": total_usd,
            "treasury_usd": treasury_usd,
            "usd_equivalent_total": total_usd + treasury_usd,
            "richest": richest[0] if richest else None,
        }

    async def inventory_transfer(
        self,
        actor: dict[str, Any],
        target: dict[str, Any],
        item_name: str,
        quantity: int,
    ) -> None:
        if quantity <= 0:
            raise ServiceError("Количество должно быть больше нуля.")
        if actor["telegram_id"] == target["telegram_id"]:
            raise ServiceError("Нельзя передавать предметы самому себе.")
        async with self._write_lock:
            async with self.db.transaction() as conn:
                await self._change_item_conn(conn, actor["telegram_id"], item_name, -quantity)
                await self._change_item_conn(conn, target["telegram_id"], item_name, quantity)

    async def refuel(self, actor: dict[str, Any], amount: int | None = None) -> dict[str, int]:
        user = await self.get_user(actor["telegram_id"])
        if user is None:
            raise ServiceError("Профиль не найден.")
        current = int(user["car_fuel"])
        target_fill = 100 - current if amount is None else amount
        if target_fill <= 0:
            raise ServiceError("Бак уже полный.")
        target_fill = clamp(target_fill, 1, 100 - current)
        cost = target_fill * 2

        async with self._write_lock:
            async with self.db.transaction() as conn:
                await self._change_balance_conn(conn, actor["telegram_id"], "usd", -cost)
                treasury = await self._change_treasury_conn(conn, cost)
                await conn.execute(
                    "UPDATE users SET car_fuel = ?, updated_at = ? WHERE telegram_id = ?",
                    (current + target_fill, self.now_iso(), actor["telegram_id"]),
                )
                await self._log_transaction_conn(
                    conn,
                    actor_id=actor["telegram_id"],
                    source_kind="user",
                    source_id=actor["telegram_id"],
                    target_kind="treasury",
                    target_id=None,
                    currency="usd",
                    amount=cost,
                    kind="refuel",
                    description=f"Заправка транспорта на {target_fill}%",
                )
        return {"fuel_added": target_fill, "cost_usd": cost, "treasury_usd": treasury}

    async def donate_to_treasury(self, actor: dict[str, Any], amount: int) -> int:
        if amount <= 0:
            raise ServiceError("Сумма пожертвования должна быть больше нуля.")
        async with self._write_lock:
            async with self.db.transaction() as conn:
                await self._change_balance_conn(conn, actor["telegram_id"], "usd", -amount)
                treasury = await self._change_treasury_conn(conn, amount)
                await self._log_transaction_conn(
                    conn,
                    actor_id=actor["telegram_id"],
                    source_kind="user",
                    source_id=actor["telegram_id"],
                    target_kind="treasury",
                    target_id=None,
                    currency="usd",
                    amount=amount,
                    kind="donate",
                    description="Добровольное пополнение казны",
                )
        return treasury

    async def treasury_withdraw(
        self,
        actor: dict[str, Any],
        target: dict[str, Any],
        amount: int,
    ) -> int:
        if actor["role"] not in {"president", "owner"}:
            raise ServiceError("Снимать деньги из казны может только президент или владелец.")
        if amount <= 0:
            raise ServiceError("Сумма должна быть положительной.")
        async with self._write_lock:
            async with self.db.transaction() as conn:
                treasury = await self._change_treasury_conn(conn, -amount)
                await self._change_balance_conn(conn, target["telegram_id"], "usd", amount)
                await self._log_transaction_conn(
                    conn,
                    actor_id=actor["telegram_id"],
                    source_kind="treasury",
                    source_id=None,
                    target_kind="user",
                    target_id=target["telegram_id"],
                    currency="usd",
                    amount=amount,
                    kind="treasury_withdraw",
                    description="Выплата из казны штата",
                )
        return treasury

    async def treasury_snapshot(self) -> dict[str, Any]:
        staff_count = int(await self.db.fetchval("SELECT COUNT(*) FROM users WHERE is_government = 1") or 0)
        taxes = await self.list_active_taxes()
        return {
            "treasury_usd": await self.get_treasury_usd(),
            "gov_salary_usd": int(await self.get_meta("gov_salary_usd", str(self.settings.default_gov_salary_usd))),
            "staff_count": staff_count,
            "taxes": taxes,
        }

    def _ensure_admin(self, actor: dict[str, Any]) -> None:
        if actor["role"] not in {"admin", "owner"}:
            raise ServiceError("Эта команда доступна только администраторам и владельцу.")

    def _ensure_owner(self, actor: dict[str, Any]) -> None:
        if actor["role"] != "owner":
            raise ServiceError("Эта команда доступна только владельцу.")

    def _ensure_president(self, actor: dict[str, Any]) -> None:
        if actor["role"] not in {"president", "owner"}:
            raise ServiceError("Эта команда доступна только президенту и владельцу.")

    def _ensure_official(self, actor: dict[str, Any]) -> None:
        if actor["role"] in {"owner", "admin", "president"}:
            return
        if not int(actor["is_government"]):
            raise ServiceError("Эта команда доступна только государственным сотрудникам.")

    async def set_role(self, actor: dict[str, Any], target: dict[str, Any], role: str) -> dict[str, Any]:
        self._ensure_owner(actor)
        if target["telegram_id"] in self.settings.owner_ids and role != "owner":
            raise ServiceError("Основного владельца нельзя понизить.")
        async with self._write_lock:
            async with self.db.transaction() as conn:
                if role == "president":
                    await conn.execute(
                        "UPDATE users SET role = 'citizen' WHERE role = 'president' AND telegram_id <> ?",
                        (target["telegram_id"],),
                    )
                await conn.execute(
                    "UPDATE users SET role = ?, updated_at = ? WHERE telegram_id = ?",
                    (role, self.now_iso(), target["telegram_id"]),
                )
        updated = await self.get_user(target["telegram_id"])
        if updated is None:
            raise ServiceError("Не удалось обновить роль пользователя.")
        return updated

    async def remove_president(self, actor: dict[str, Any]) -> int:
        self._ensure_owner(actor)
        async with self._write_lock:
            async with self.db.transaction() as conn:
                cursor = await conn.execute(
                    "UPDATE users SET role = 'citizen', updated_at = ? WHERE role = 'president'",
                    (self.now_iso(),),
                )
                return int(cursor.rowcount or 0)

    async def adjust_money(
        self,
        actor: dict[str, Any],
        target: dict[str, Any],
        amount: int,
        currency: str,
        *,
        add: bool,
    ) -> None:
        self._ensure_admin(actor)
        currency = normalize_currency(currency)
        if amount <= 0:
            raise ServiceError("Сумма должна быть больше нуля.")
        delta = amount if add else -amount
        kind = "admin_add" if add else "admin_remove"
        source_kind = "system" if add else "user"
        target_kind = "user" if add else "system"
        source_id = None if add else target["telegram_id"]
        target_id = target["telegram_id"] if add else None

        async with self._write_lock:
            async with self.db.transaction() as conn:
                await self._change_balance_conn(conn, target["telegram_id"], currency, delta)
                await self._log_transaction_conn(
                    conn,
                    actor_id=actor["telegram_id"],
                    source_kind=source_kind,
                    source_id=source_id,
                    target_kind=target_kind,
                    target_id=target_id,
                    currency=currency,
                    amount=amount,
                    kind=kind,
                    description="Ручная корректировка администратора",
                )

    async def set_government_status(self, actor: dict[str, Any], target: dict[str, Any], active: bool) -> dict[str, Any]:
        self._ensure_president(actor)
        async with self._write_lock:
            async with self.db.transaction() as conn:
                await conn.execute(
                    "UPDATE users SET is_government = ?, updated_at = ? WHERE telegram_id = ?",
                    (1 if active else 0, self.now_iso(), target["telegram_id"]),
                )
        updated = await self.get_user(target["telegram_id"])
        if updated is None:
            raise ServiceError("Не удалось обновить государственный статус.")
        return updated

    async def set_government_salary(self, actor: dict[str, Any], amount: int) -> int:
        self._ensure_president(actor)
        if amount <= 0:
            raise ServiceError("Зарплата должна быть больше нуля.")
        await self.set_meta("gov_salary_usd", str(amount))
        return amount

    async def add_item(self, actor: dict[str, Any], target: dict[str, Any], item_name: str, quantity: int) -> None:
        self._ensure_admin(actor)
        if quantity <= 0:
            raise ServiceError("Количество должно быть больше нуля.")
        async with self._write_lock:
            async with self.db.transaction() as conn:
                await self._change_item_conn(conn, target["telegram_id"], item_name, quantity)

    async def remove_item(self, actor: dict[str, Any], target: dict[str, Any], item_name: str, quantity: int) -> None:
        self._ensure_admin(actor)
        if quantity <= 0:
            raise ServiceError("Количество должно быть больше нуля.")
        async with self._write_lock:
            async with self.db.transaction() as conn:
                await self._change_item_conn(conn, target["telegram_id"], item_name, -quantity)

    async def issue_fine(
        self,
        actor: dict[str, Any],
        target: dict[str, Any],
        amount: int,
        reason: str,
    ) -> dict[str, Any]:
        self._ensure_official(actor)
        if amount <= 0:
            raise ServiceError("Сумма штрафа должна быть больше нуля.")
        if actor["telegram_id"] == target["telegram_id"]:
            raise ServiceError("Нельзя выписать штраф самому себе.")
        issued_at = self.now()
        due_at = issued_at + timedelta(days=self.settings.fine_deadline_days)
        async with self._write_lock:
            async with self.db.transaction() as conn:
                cursor = await conn.execute(
                    """
                    INSERT INTO fines(target_id, issuer_id, amount_usd, reason, status, issued_at, due_at)
                    VALUES(?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        target["telegram_id"],
                        actor["telegram_id"],
                        amount,
                        reason.strip(),
                        issued_at.isoformat(timespec="seconds"),
                        due_at.isoformat(timespec="seconds"),
                    ),
                )
                fine_id = int(cursor.lastrowid)
        row = await self.db.fetchone(
            """
            SELECT f.*, u.full_name AS target_name, i.full_name AS issuer_name
            FROM fines f
            JOIN users u ON u.telegram_id = f.target_id
            LEFT JOIN users i ON i.telegram_id = f.issuer_id
            WHERE f.id = ?
            """,
            (fine_id,),
        )
        if row is None:
            raise ServiceError("Не удалось сохранить штраф.")
        return dict(row)

    async def pay_fine(self, actor: dict[str, Any], fine_id: int) -> dict[str, Any]:
        async with self._write_lock:
            async with self.db.transaction() as conn:
                fine = await self._fetchone(
                    conn,
                    """
                    SELECT * FROM fines
                    WHERE id = ? AND status IN ('active', 'overdue')
                    """,
                    (fine_id,),
                )
                if fine is None:
                    raise ServiceError("Активный штраф с таким номером не найден.")
                if int(fine["target_id"]) != actor["telegram_id"]:
                    raise ServiceError("Этот штраф не относится к вашему профилю.")
                amount = int(fine["amount_usd"])
                await self._change_balance_conn(conn, actor["telegram_id"], "usd", -amount)
                treasury = await self._change_treasury_conn(conn, amount)
                await conn.execute(
                    """
                    UPDATE fines
                    SET status = 'paid', paid_at = ?
                    WHERE id = ?
                    """,
                    (self.now_iso(), fine_id),
                )
                await self._log_transaction_conn(
                    conn,
                    actor_id=actor["telegram_id"],
                    source_kind="user",
                    source_id=actor["telegram_id"],
                    target_kind="treasury",
                    target_id=None,
                    currency="usd",
                    amount=amount,
                    kind="fine_payment",
                    description=f"Оплата штрафа #{fine_id}",
                )
        result = dict(fine)
        result["treasury_usd"] = treasury
        return result

    async def remove_paid_fines(self, actor: dict[str, Any], target: dict[str, Any]) -> int:
        self._ensure_official(actor)
        async with self._write_lock:
            async with self.db.transaction() as conn:
                cursor = await conn.execute(
                    """
                    UPDATE fines
                    SET status = 'removed', removed_at = ?
                    WHERE target_id = ? AND status = 'paid'
                    """,
                    (self.now_iso(), target["telegram_id"]),
                )
                count = int(cursor.rowcount or 0)
                if count <= 0:
                    raise ServiceError("У этого игрока нет оплаченных штрафов для снятия из списка.")
        return count

    async def list_fines(self, *, target_id: int | None = None, page: int = 0) -> Page:
        page = max(page, 0)
        where = []
        params: list[Any] = []
        if target_id is not None:
            where.append("f.target_id = ?")
            params.append(target_id)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        count = int(
            await self.db.fetchval(
                f"SELECT COUNT(*) FROM fines f {where_sql}",
                tuple(params),
            )
            or 0
        )
        total_pages = max((count + PAGE_SIZE - 1) // PAGE_SIZE, 1)
        page = min(page, total_pages - 1)
        params.extend([PAGE_SIZE, page * PAGE_SIZE])
        rows = await self.db.fetchall(
            f"""
            SELECT
                f.*,
                t.full_name AS target_name,
                i.full_name AS issuer_name
            FROM fines f
            JOIN users t ON t.telegram_id = f.target_id
            LEFT JOIN users i ON i.telegram_id = f.issuer_id
            {where_sql}
            ORDER BY f.id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params),
        )
        return Page(items=[dict(row) for row in rows], page=page, total_pages=total_pages)

    async def issue_wanted(
        self,
        actor: dict[str, Any],
        full_name_text: str,
        appearance: str,
        reason: str,
        *,
        system_generated: bool = False,
    ) -> dict[str, Any]:
        if not system_generated:
            self._ensure_official(actor)
        async with self._write_lock:
            async with self.db.transaction() as conn:
                cursor = await conn.execute(
                    """
                    INSERT INTO wanted_cases(
                        full_name_text, appearance, reason,
                        issuer_id, status, created_at, system_generated
                    )
                    VALUES(?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        full_name_text.strip(),
                        appearance.strip(),
                        reason.strip(),
                        None if system_generated else actor["telegram_id"],
                        self.now_iso(),
                        1 if system_generated else 0,
                    ),
                )
                wanted_id = int(cursor.lastrowid)
        row = await self.db.fetchone(
            """
            SELECT
                w.*,
                i.full_name AS issuer_name
            FROM wanted_cases w
            LEFT JOIN users i ON i.telegram_id = w.issuer_id
            WHERE w.id = ?
            """,
            (wanted_id,),
        )
        if row is None:
            raise ServiceError("Не удалось сохранить розыск.")
        return dict(row)

    async def remove_wanted(self, actor: dict[str, Any], wanted_id: int) -> int:
        self._ensure_official(actor)
        async with self._write_lock:
            async with self.db.transaction() as conn:
                cursor = await conn.execute(
                    """
                    UPDATE wanted_cases
                    SET status = 'removed', removed_at = ?, removed_by = ?
                    WHERE id = ? AND status = 'active'
                    """,
                    (self.now_iso(), actor["telegram_id"], wanted_id),
                )
                count = int(cursor.rowcount or 0)
                if count <= 0:
                    raise ServiceError("Активный розыск с таким номером не найден.")
        return count

    async def list_wanteds(self, page: int = 0) -> Page:
        page = max(page, 0)
        count = int(
            await self.db.fetchval(
                "SELECT COUNT(*) FROM wanted_cases WHERE status = 'active'"
            )
            or 0
        )
        total_pages = max((count + PAGE_SIZE - 1) // PAGE_SIZE, 1)
        page = min(page, total_pages - 1)
        rows = await self.db.fetchall(
            """
            SELECT
                w.*,
                i.full_name AS issuer_name
            FROM wanted_cases w
            LEFT JOIN users i ON i.telegram_id = w.issuer_id
            WHERE w.status = 'active'
            ORDER BY w.id DESC
            LIMIT ? OFFSET ?
            """,
            (PAGE_SIZE, page * PAGE_SIZE),
        )
        return Page(items=[dict(row) for row in rows], page=page, total_pages=total_pages)

    async def maybe_send_private(self, bot: Bot, user_id: int, text: str) -> bool:
        try:
            await bot.send_message(user_id, text)
            return True
        except TelegramAPIError:
            return False

    async def notify_government_staff(self, bot: Bot, text: str) -> int:
        rows = await self.db.fetchall(
            """
            SELECT telegram_id
            FROM users
            WHERE is_government = 1 OR role IN ('admin', 'president', 'owner')
            """
        )
        delivered = 0
        for row in rows:
            if await self.maybe_send_private(bot, int(row["telegram_id"]), text):
                delivered += 1
        return delivered

    async def grant_special_access(self, actor: dict[str, Any], target: dict[str, Any], access_kind: str) -> None:
        self._ensure_owner(actor)
        if access_kind not in {"mega", "conglomerate"}:
            raise ServiceError("Неизвестный тип специального доступа.")
        column = "mega_access" if access_kind == "mega" else "conglomerate_access"
        async with self._write_lock:
            async with self.db.transaction() as conn:
                await conn.execute(
                    """
                    INSERT INTO special_access(user_id, mega_access, conglomerate_access, updated_at)
                    VALUES(?, 0, 0, ?)
                    ON CONFLICT(user_id) DO NOTHING
                    """,
                    (target["telegram_id"], self.now_iso()),
                )
                await conn.execute(
                    f"UPDATE special_access SET {column} = 1, updated_at = ? WHERE user_id = ?",
                    (self.now_iso(), target["telegram_id"]),
                )

    async def register_organization(
        self,
        actor: dict[str, Any],
        org_type: str,
        name: str,
        direction: str,
        short_description: str,
        starting_capital: int,
    ) -> dict[str, Any]:
        config = self._organization_config(org_type)
        existing = await self._get_organization_by_owner(actor["telegram_id"])
        if existing is not None:
            raise ServiceError("У вас уже есть активная организация. Сначала закройте её.")
        if config["requires_access"] and actor["role"] != "owner":
            access_row = await self.db.fetchone(
                "SELECT * FROM special_access WHERE user_id = ?",
                (actor["telegram_id"],),
            )
            if access_row is None or not int(access_row["mega_access" if config["requires_access"] == "mega" else "conglomerate_access"]):
                raise ServiceError("Для регистрации этой организации требуется отдельное разрешение владельца.")
        if starting_capital <= 0:
            raise ServiceError("Начальный капитал должен быть больше нуля.")
        clean_name = name.strip()
        if len(clean_name) < 3:
            raise ServiceError("Название организации должно содержать минимум 3 символа.")
        taken = await self.db.fetchone(
            "SELECT id FROM organizations WHERE name = ? COLLATE NOCASE AND status = 'active'",
            (clean_name,),
        )
        if taken is not None:
            raise ServiceError("Организация с таким названием уже существует.")
        clean_description = short_description.strip()
        if len(clean_description) < 5:
            raise ServiceError("Краткое описание слишком короткое.")
        clean_direction = self._normalize_business_direction(org_type, direction)
        total_required = int(config["registration_fee"]) + starting_capital

        async with self._write_lock:
            async with self.db.transaction() as conn:
                if total_required > 0:
                    await self._change_balance_conn(conn, actor["telegram_id"], "usd", -total_required)
                cursor = await conn.execute(
                    """
                    INSERT INTO organizations(
                        owner_id, org_type, name, direction, short_description,
                        capital_usd, payroll_usd, status, created_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, 0, 'active', ?)
                    """,
                    (
                        actor["telegram_id"],
                        org_type,
                        clean_name,
                        clean_direction,
                        clean_description,
                        starting_capital,
                        self.now_iso(),
                    ),
                )
                organization_id = int(cursor.lastrowid)
                await conn.execute(
                    """
                    INSERT INTO organization_members(organization_id, user_id, member_type, role_id, joined_at)
                    VALUES(?, ?, 'owner', NULL, ?)
                    """,
                    (organization_id, actor["telegram_id"], self.now_iso()),
                )
                await self._log_transaction_conn(
                    conn,
                    actor_id=actor["telegram_id"],
                    source_kind="user",
                    source_id=actor["telegram_id"],
                    target_kind="organization",
                    target_id=organization_id,
                    currency="usd",
                    amount=starting_capital,
                    kind="org_capital_seed",
                    description=f"Стартовый капитал для организации {clean_name}",
                )
                registration_fee = int(config["registration_fee"])
                if registration_fee > 0:
                    await self._log_transaction_conn(
                        conn,
                        actor_id=actor["telegram_id"],
                        source_kind="user",
                        source_id=actor["telegram_id"],
                        target_kind="system",
                        target_id=None,
                        currency="usd",
                        amount=registration_fee,
                        kind="org_registration_fee",
                        description=f"Регистрационный взнос за {config['label'].lower()}",
                    )
        organization = await self.organization_panel(actor["telegram_id"])
        if organization is None:
            raise ServiceError("Не удалось зарегистрировать организацию.")
        return organization

    async def organization_panel(self, owner_id: int, allowed_types: set[str] | None = None) -> dict[str, Any] | None:
        organization = await self._get_organization_by_owner(owner_id, allowed_types)
        if organization is None:
            return None
        organization_id = int(organization["id"])
        staff_count = int(
            await self.db.fetchval(
                """
                SELECT COUNT(*)
                FROM organization_members
                WHERE organization_id = ? AND member_type <> 'owner'
                """,
                (organization_id,),
            )
            or 0
        )
        invite_count = int(
            await self.db.fetchval(
                "SELECT COUNT(*) FROM organization_invites WHERE organization_id = ? AND status = 'pending'",
                (organization_id,),
            )
            or 0
        )
        role_count = int(
            await self.db.fetchval(
                "SELECT COUNT(*) FROM organization_roles WHERE organization_id = ?",
                (organization_id,),
            )
            or 0
        )
        organization["staff_count"] = staff_count
        organization["pending_invites"] = invite_count
        organization["role_count"] = role_count
        organization["type_label"] = self._organization_config(str(organization["org_type"]))["label"]
        return organization

    async def list_organization_staff(self, actor: dict[str, Any], allowed_types: set[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        organization = await self._require_owned_organization(actor, allowed_types)
        rows = await self.db.fetchall(
            """
            SELECT
                m.*,
                u.full_name,
                u.telegram_id,
                r.name AS custom_role_name
            FROM organization_members m
            JOIN users u ON u.telegram_id = m.user_id
            LEFT JOIN organization_roles r ON r.id = m.role_id
            WHERE m.organization_id = ?
            ORDER BY CASE WHEN m.member_type = 'owner' THEN 0 ELSE 1 END, u.full_name COLLATE NOCASE ASC
            """,
            (organization["id"],),
        )
        return organization, [dict(row) for row in rows]

    async def invite_organization_staff(self, actor: dict[str, Any], target: dict[str, Any], allowed_types: set[str]) -> dict[str, Any]:
        organization = await self._require_owned_organization(actor, allowed_types)
        if actor["telegram_id"] == target["telegram_id"]:
            raise ServiceError("Себя приглашать не нужно.")
        if await self.get_user_organization(target["telegram_id"]) is not None:
            raise ServiceError("У пользователя уже есть активная организация или должность.")
        existing_member = await self._get_organization_member_row(int(organization["id"]), target["telegram_id"])
        if existing_member is not None:
            raise ServiceError("Этот пользователь уже состоит в вашей организации.")
        pending = await self.db.fetchone(
            """
            SELECT *
            FROM organization_invites
            WHERE organization_id = ? AND user_id = ? AND status = 'pending'
            """,
            (organization["id"], target["telegram_id"]),
        )
        if pending is not None:
            raise ServiceError("Для этого пользователя уже висит активное приглашение.")
        async with self._write_lock:
            async with self.db.transaction() as conn:
                cursor = await conn.execute(
                    """
                    INSERT INTO organization_invites(organization_id, user_id, invited_by, status, created_at)
                    VALUES(?, ?, ?, 'pending', ?)
                    """,
                    (organization["id"], target["telegram_id"], actor["telegram_id"], self.now_iso()),
                )
                invite_id = int(cursor.lastrowid)
        invite = await self.db.fetchone(
            """
            SELECT i.*, o.name AS organization_name, o.org_type
            FROM organization_invites i
            JOIN organizations o ON o.id = i.organization_id
            WHERE i.id = ?
            """,
            (invite_id,),
        )
        if invite is None:
            raise ServiceError("Не удалось создать приглашение.")
        return dict(invite)

    async def list_pending_organization_invites(self, user_id: int) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            """
            SELECT
                i.*,
                o.name AS organization_name,
                o.org_type,
                o.direction,
                o.short_description,
                u.full_name AS inviter_name
            FROM organization_invites i
            JOIN organizations o ON o.id = i.organization_id
            JOIN users u ON u.telegram_id = i.invited_by
            WHERE i.user_id = ? AND i.status = 'pending' AND o.status = 'active'
            ORDER BY i.id DESC
            """,
            (user_id,),
        )
        return [dict(row) for row in rows]

    async def respond_organization_invite(self, actor: dict[str, Any], invite_id: int, accept: bool) -> dict[str, Any]:
        invite = await self.db.fetchone(
            """
            SELECT i.*, o.name AS organization_name, o.org_type, o.status AS organization_status
            FROM organization_invites i
            JOIN organizations o ON o.id = i.organization_id
            WHERE i.id = ? AND i.status = 'pending'
            """,
            (invite_id,),
        )
        if invite is None:
            raise ServiceError("Активное приглашение с таким номером не найдено.")
        if int(invite["user_id"]) != actor["telegram_id"]:
            raise ServiceError("Это приглашение адресовано не вам.")
        if str(invite["organization_status"]) != "active":
            raise ServiceError("Организация уже недоступна.")
        if accept and await self.get_user_organization(actor["telegram_id"]) is not None:
            raise ServiceError("Сначала выйдите из текущей организации или закройте её.")
        async with self._write_lock:
            async with self.db.transaction() as conn:
                if accept:
                    await conn.execute(
                        """
                        INSERT INTO organization_members(organization_id, user_id, member_type, role_id, joined_at)
                        VALUES(?, ?, 'staff', NULL, ?)
                        """,
                        (invite["organization_id"], actor["telegram_id"], self.now_iso()),
                    )
                await conn.execute(
                    """
                    UPDATE organization_invites
                    SET status = ?, responded_at = ?
                    WHERE id = ?
                    """,
                    ("accepted" if accept else "declined", self.now_iso(), invite_id),
                )
        return dict(invite)

    async def set_organization_payroll(self, actor: dict[str, Any], allowed_types: set[str], amount: int) -> dict[str, Any]:
        if amount < 0:
            raise ServiceError("Зарплата не может быть отрицательной.")
        organization = await self._require_owned_organization(actor, allowed_types)
        async with self._write_lock:
            async with self.db.transaction() as conn:
                await conn.execute(
                    "UPDATE organizations SET payroll_usd = ? WHERE id = ?",
                    (amount, organization["id"]),
                )
        updated = await self.organization_panel(actor["telegram_id"], allowed_types)
        if updated is None:
            raise ServiceError("Не удалось обновить зарплату организации.")
        return updated

    async def add_organization_capital(self, actor: dict[str, Any], allowed_types: set[str], amount: int) -> dict[str, Any]:
        if amount <= 0:
            raise ServiceError("Сумма пополнения должна быть больше нуля.")
        organization = await self._require_owned_organization(actor, allowed_types)
        async with self._write_lock:
            async with self.db.transaction() as conn:
                await self._change_balance_conn(conn, actor["telegram_id"], "usd", -amount)
                await conn.execute(
                    "UPDATE organizations SET capital_usd = capital_usd + ? WHERE id = ?",
                    (amount, organization["id"]),
                )
                await self._log_transaction_conn(
                    conn,
                    actor_id=actor["telegram_id"],
                    source_kind="user",
                    source_id=actor["telegram_id"],
                    target_kind="organization",
                    target_id=organization["id"],
                    currency="usd",
                    amount=amount,
                    kind="org_capital_add",
                    description=f"Пополнение капитала организации {organization['name']}",
                )
        updated = await self.organization_panel(actor["telegram_id"], allowed_types)
        if updated is None:
            raise ServiceError("Не удалось обновить капитал организации.")
        return updated

    async def create_organization_role(self, actor: dict[str, Any], allowed_types: set[str], role_name: str) -> dict[str, Any]:
        organization = await self._require_owned_organization(actor, allowed_types)
        clean_name = role_name.strip()
        if len(clean_name) < 2:
            raise ServiceError("Название роли слишком короткое.")
        limit = self._organization_role_limit(str(organization["org_type"]))
        current_count = int(
            await self.db.fetchval(
                "SELECT COUNT(*) FROM organization_roles WHERE organization_id = ?",
                (organization["id"],),
            )
            or 0
        )
        duplicate = await self.db.fetchone(
            """
            SELECT id
            FROM organization_roles
            WHERE organization_id = ? AND name = ? COLLATE NOCASE
            """,
            (organization["id"], clean_name),
        )
        if duplicate is not None:
            raise ServiceError("Такая роль уже существует.")
        if limit is not None and current_count >= limit:
            raise ServiceError("Лимит кастомных ролей для этой организации уже достигнут.")
        async with self._write_lock:
            async with self.db.transaction() as conn:
                await conn.execute(
                    """
                    INSERT INTO organization_roles(organization_id, name, created_at)
                    VALUES(?, ?, ?)
                    """,
                    (organization["id"], clean_name, self.now_iso()),
                )
        row = await self.db.fetchone(
            """
            SELECT *
            FROM organization_roles
            WHERE organization_id = ? AND name = ? COLLATE NOCASE
            ORDER BY id DESC
            LIMIT 1
            """,
            (organization["id"], clean_name),
        )
        if row is None:
            raise ServiceError("Не удалось создать роль.")
        return dict(row)

    async def set_organization_member_role(
        self,
        actor: dict[str, Any],
        target: dict[str, Any],
        allowed_types: set[str],
        role_name: str,
    ) -> dict[str, Any]:
        organization = await self._require_owned_organization(actor, allowed_types)
        member = await self._get_organization_member_row(int(organization["id"]), target["telegram_id"])
        if member is None:
            raise ServiceError("Пользователь не состоит в этой организации.")
        if str(member["member_type"]) == "owner":
            raise ServiceError("Владельцу не нужно назначать кастомную роль.")
        role = await self.db.fetchone(
            """
            SELECT *
            FROM organization_roles
            WHERE organization_id = ? AND name = ? COLLATE NOCASE
            LIMIT 1
            """,
            (organization["id"], role_name.strip()),
        )
        if role is None:
            raise ServiceError("Сначала создайте эту роль в организации.")
        async with self._write_lock:
            async with self.db.transaction() as conn:
                await conn.execute(
                    """
                    UPDATE organization_members
                    SET role_id = ?
                    WHERE organization_id = ? AND user_id = ?
                    """,
                    (role["id"], organization["id"], target["telegram_id"]),
                )
        updated = await self._get_organization_member_row(int(organization["id"]), target["telegram_id"])
        if updated is None:
            raise ServiceError("Не удалось обновить роль сотрудника.")
        return updated

    async def delete_organization(self, actor: dict[str, Any], allowed_types: set[str]) -> dict[str, Any]:
        organization = await self._require_owned_organization(actor, allowed_types)
        refund_percent = self._organization_refund_percent(str(organization["org_type"]))
        capital = int(organization["capital_usd"])
        refund = capital * refund_percent // 100
        async with self._write_lock:
            async with self.db.transaction() as conn:
                if refund > 0:
                    await self._change_balance_conn(conn, actor["telegram_id"], "usd", refund)
                await conn.execute(
                    """
                    UPDATE organizations
                    SET status = 'deleted', deleted_at = ?
                    WHERE id = ?
                    """,
                    (self.now_iso(), organization["id"]),
                )
                await conn.execute(
                    """
                    UPDATE organization_invites
                    SET status = 'declined', responded_at = ?
                    WHERE organization_id = ? AND status = 'pending'
                    """,
                    (self.now_iso(), organization["id"]),
                )
                if refund > 0:
                    await self._log_transaction_conn(
                        conn,
                        actor_id=actor["telegram_id"],
                        source_kind="organization",
                        source_id=organization["id"],
                        target_kind="user",
                        target_id=actor["telegram_id"],
                        currency="usd",
                        amount=refund,
                        kind="org_delete_refund",
                        description=f"Возврат капитала при закрытии {organization['name']}",
                    )
        organization["refund_usd"] = refund
        organization["burned_usd"] = capital - refund
        return organization

    async def invest_in_organization(self, actor: dict[str, Any], organization_name: str, amount: int) -> dict[str, Any]:
        if amount <= 0:
            raise ServiceError("Сумма инвестиции должна быть больше нуля.")
        organization = await self._get_organization_by_name(organization_name)
        if organization is None:
            raise ServiceError("Активная организация с таким названием не найдена.")
        async with self._write_lock:
            async with self.db.transaction() as conn:
                await self._change_balance_conn(conn, actor["telegram_id"], "usd", -amount)
                await conn.execute(
                    "UPDATE organizations SET capital_usd = capital_usd + ? WHERE id = ?",
                    (amount, organization["id"]),
                )
                await self._log_transaction_conn(
                    conn,
                    actor_id=actor["telegram_id"],
                    source_kind="user",
                    source_id=actor["telegram_id"],
                    target_kind="organization",
                    target_id=organization["id"],
                    currency="usd",
                    amount=amount,
                    kind="invest",
                    description=f"Инвестиция в {organization['name']}",
                )
        updated = await self._get_organization_by_name(str(organization["name"]))
        if updated is None:
            raise ServiceError("Не удалось обновить капитал организации.")
        return updated

    async def create_sale_post(self, actor: dict[str, Any], item_name: str, quantity: int, price_usd: int, description: str) -> dict[str, Any]:
        if quantity <= 0:
            raise ServiceError("Количество должно быть больше нуля.")
        if price_usd <= 0:
            raise ServiceError("Цена должна быть больше нуля.")
        clean_item = item_name.strip()
        if not clean_item:
            raise ServiceError("Нужно указать название предмета.")
        body = description.strip() or f"Продажа предмета {clean_item}"
        async with self._write_lock:
            async with self.db.transaction() as conn:
                await self._change_item_conn(conn, actor["telegram_id"], clean_item, -quantity)
                cursor = await conn.execute(
                    """
                    INSERT INTO market_posts(
                        owner_id, post_kind, category_tag, title, body,
                        item_name, quantity, remaining_quantity, price_usd, status, created_at
                    )
                    VALUES(?, 'sale', 'Продажа', ?, ?, ?, ?, ?, ?, 'active', ?)
                    """,
                    (
                        actor["telegram_id"],
                        clean_item,
                        body,
                        clean_item,
                        quantity,
                        quantity,
                        price_usd,
                        self.now_iso(),
                    ),
                )
                post_id = int(cursor.lastrowid)
        row = await self.db.fetchone(
            """
            SELECT p.*, u.full_name AS owner_name
            FROM market_posts p
            JOIN users u ON u.telegram_id = p.owner_id
            WHERE p.id = ?
            """,
            (post_id,),
        )
        if row is None:
            raise ServiceError("Не удалось создать объявление о продаже.")
        return dict(row)

    async def create_classified_post(self, actor: dict[str, Any], post_kind: str, text: str) -> dict[str, Any]:
        category_tag = {"hire": "ИщюСотрудника", "work": "ИщюРаботу"}.get(post_kind)
        if category_tag is None:
            raise ServiceError("Неизвестный тип объявления.")
        body = text.strip()
        if len(body) < 10:
            raise ServiceError("Текст объявления слишком короткий.")
        title = body.splitlines()[0][:80]
        async with self._write_lock:
            async with self.db.transaction() as conn:
                cursor = await conn.execute(
                    """
                    INSERT INTO market_posts(
                        owner_id, post_kind, category_tag, title, body,
                        item_name, quantity, remaining_quantity, price_usd, status, created_at
                    )
                    VALUES(?, ?, ?, ?, ?, NULL, 0, 0, 0, 'active', ?)
                    """,
                    (actor["telegram_id"], post_kind, category_tag, title, body, self.now_iso()),
                )
                post_id = int(cursor.lastrowid)
        row = await self.db.fetchone(
            """
            SELECT p.*, u.full_name AS owner_name
            FROM market_posts p
            JOIN users u ON u.telegram_id = p.owner_id
            WHERE p.id = ?
            """,
            (post_id,),
        )
        if row is None:
            raise ServiceError("Не удалось опубликовать объявление.")
        return dict(row)

    async def list_market_sales(self, page: int = 0) -> Page:
        page = max(page, 0)
        count = int(
            await self.db.fetchval(
                """
                SELECT COUNT(*)
                FROM market_posts
                WHERE post_kind = 'sale' AND status = 'active' AND remaining_quantity > 0
                """
            )
            or 0
        )
        total_pages = max((count + PAGE_SIZE - 1) // PAGE_SIZE, 1)
        page = min(page, total_pages - 1)
        rows = await self.db.fetchall(
            """
            SELECT p.*, u.full_name AS owner_name
            FROM market_posts p
            JOIN users u ON u.telegram_id = p.owner_id
            WHERE p.post_kind = 'sale' AND p.status = 'active' AND p.remaining_quantity > 0
            ORDER BY p.id DESC
            LIMIT ? OFFSET ?
            """,
            (PAGE_SIZE, page * PAGE_SIZE),
        )
        return Page(items=[dict(row) for row in rows], page=page, total_pages=total_pages)

    async def buy_market_sale(self, actor: dict[str, Any], post_id: int, quantity: int) -> dict[str, Any]:
        if quantity <= 0:
            raise ServiceError("Количество должно быть больше нуля.")
        async with self._write_lock:
            async with self.db.transaction() as conn:
                post = await self._fetchone(
                    conn,
                    """
                    SELECT *
                    FROM market_posts
                    WHERE id = ? AND post_kind = 'sale' AND status = 'active'
                    """,
                    (post_id,),
                )
                if post is None:
                    raise ServiceError("Активное объявление о продаже не найдено.")
                if int(post["owner_id"]) == actor["telegram_id"]:
                    raise ServiceError("Нельзя покупать свой же лот.")
                remaining = int(post["remaining_quantity"])
                if quantity > remaining:
                    raise ServiceError("В лоте не хватает такого количества предметов.")
                total_price = int(post["price_usd"]) * quantity
                await self._change_balance_conn(conn, actor["telegram_id"], "usd", -total_price)
                await self._change_balance_conn(conn, int(post["owner_id"]), "usd", total_price)
                await self._change_item_conn(conn, actor["telegram_id"], str(post["item_name"]), quantity)
                next_remaining = remaining - quantity
                await conn.execute(
                    """
                    UPDATE market_posts
                    SET remaining_quantity = ?, status = ?, closed_at = CASE WHEN ? = 0 THEN ? ELSE closed_at END
                    WHERE id = ?
                    """,
                    (
                        next_remaining,
                        "sold" if next_remaining == 0 else "active",
                        next_remaining,
                        self.now_iso(),
                        post_id,
                    ),
                )
                await self._log_transaction_conn(
                    conn,
                    actor_id=actor["telegram_id"],
                    source_kind="user",
                    source_id=actor["telegram_id"],
                    target_kind="user",
                    target_id=int(post["owner_id"]),
                    currency="usd",
                    amount=total_price,
                    kind="market_buy",
                    description=f"Покупка {quantity} x {post['item_name']} по лоту #{post_id}",
                )
        result = dict(post)
        result["bought_quantity"] = quantity
        result["total_price"] = total_price
        result["remaining_quantity"] = next_remaining
        return result

    async def collect_weekly_taxes(self) -> dict[str, int]:
        taxes = await self.list_active_taxes()
        if not taxes:
            return {"taxes_count": 0, "charged_players": 0, "collected_usd": 0}
        total_tax = sum(taxes)

        async with self._write_lock:
            async with self.db.transaction() as conn:
                players = await self._fetchall(conn, "SELECT * FROM users ORDER BY telegram_id ASC")
                charged_players = 0
                collected_usd = 0
                for player in players:
                    available = int(player["usd_balance"])
                    charge = min(available, total_tax)
                    if charge <= 0:
                        continue
                    await self._change_balance_conn(conn, int(player["telegram_id"]), "usd", -charge)
                    await self._change_treasury_conn(conn, charge)
                    await self._log_transaction_conn(
                        conn,
                        actor_id=None,
                        source_kind="user",
                        source_id=int(player["telegram_id"]),
                        target_kind="treasury",
                        target_id=None,
                        currency="usd",
                        amount=charge,
                        kind="weekly_tax",
                        description="Автоматическое воскресное удержание налогов",
                    )
                    charged_players += 1
                    collected_usd += charge
        return {"taxes_count": len(taxes), "charged_players": charged_players, "collected_usd": collected_usd}

    async def pay_government_salaries(self) -> dict[str, int]:
        salary = int(await self.get_meta("gov_salary_usd", str(self.settings.default_gov_salary_usd)))
        if salary <= 0:
            return {"salary_usd": 0, "paid_staff": 0, "total_paid": 0}

        async with self._write_lock:
            async with self.db.transaction() as conn:
                staff = await self._fetchall(
                    conn,
                    "SELECT * FROM users WHERE is_government = 1 ORDER BY telegram_id ASC",
                )
                treasury = int(await self._get_meta_conn(conn, "treasury_usd", "0"))
                paid_staff = 0
                total_paid = 0
                for worker in staff:
                    if treasury <= 0:
                        break
                    payout = min(salary, treasury)
                    await self._change_treasury_conn(conn, -payout)
                    treasury -= payout
                    await self._change_balance_conn(conn, int(worker["telegram_id"]), "usd", payout)
                    await self._log_transaction_conn(
                        conn,
                        actor_id=None,
                        source_kind="treasury",
                        source_id=None,
                        target_kind="user",
                        target_id=int(worker["telegram_id"]),
                        currency="usd",
                        amount=payout,
                        kind="government_salary",
                        description="Автоматическая зарплата государственного сотрудника",
                    )
                    paid_staff += 1
                    total_paid += payout
        return {"salary_usd": salary, "paid_staff": paid_staff, "total_paid": total_paid}

    async def pay_organization_salaries(self) -> dict[str, int]:
        async with self._write_lock:
            async with self.db.transaction() as conn:
                organizations = await self._fetchall(
                    conn,
                    """
                    SELECT *
                    FROM organizations
                    WHERE status = 'active' AND payroll_usd > 0
                    ORDER BY id ASC
                    """,
                )
                paid_staff = 0
                total_paid = 0
                organization_count = 0
                for organization in organizations:
                    salary = int(organization["payroll_usd"])
                    if salary <= 0:
                        continue
                    staff = await self._fetchall(
                        conn,
                        """
                        SELECT *
                        FROM organization_members
                        WHERE organization_id = ? AND member_type <> 'owner'
                        ORDER BY id ASC
                        """,
                        (organization["id"],),
                    )
                    if not staff:
                        continue
                    organization_count += 1
                    capital = int(organization["capital_usd"])
                    if capital <= 0:
                        continue
                    for worker in staff:
                        if capital <= 0:
                            break
                        payout = min(salary, capital)
                        await conn.execute(
                            "UPDATE organizations SET capital_usd = capital_usd - ? WHERE id = ?",
                            (payout, organization["id"]),
                        )
                        capital -= payout
                        await self._change_balance_conn(conn, int(worker["user_id"]), "usd", payout)
                        await self._log_transaction_conn(
                            conn,
                            actor_id=None,
                            source_kind="organization",
                            source_id=int(organization["id"]),
                            target_kind="user",
                            target_id=int(worker["user_id"]),
                            currency="usd",
                            amount=payout,
                            kind="organization_salary",
                            description=f"Выплата зарплаты сотруднику организации {organization['name']}",
                        )
                        paid_staff += 1
                        total_paid += payout
        return {"organizations": organization_count, "paid_staff": paid_staff, "total_paid": total_paid}

    async def _grant_organization_income(
        self,
        org_types: set[str],
        amount: int,
        *,
        kind: str,
        description_prefix: str,
    ) -> dict[str, int]:
        if amount <= 0 or not org_types:
            return {"organizations": 0, "total_paid": 0, "income_usd": 0}
        placeholders = ", ".join("?" for _ in org_types)
        params = tuple(sorted(org_types))
        async with self._write_lock:
            async with self.db.transaction() as conn:
                organizations = await self._fetchall(
                    conn,
                    f"""
                    SELECT *
                    FROM organizations
                    WHERE status = 'active' AND org_type IN ({placeholders})
                    ORDER BY id ASC
                    """,
                    params,
                )
                credited = 0
                total_paid = 0
                for organization in organizations:
                    await conn.execute(
                        "UPDATE organizations SET capital_usd = capital_usd + ? WHERE id = ?",
                        (amount, organization["id"]),
                    )
                    await self._log_transaction_conn(
                        conn,
                        actor_id=None,
                        source_kind="system",
                        source_id=None,
                        target_kind="organization",
                        target_id=int(organization["id"]),
                        currency="usd",
                        amount=amount,
                        kind=kind,
                        description=f"{description_prefix} {organization['name']}",
                    )
                    credited += 1
                    total_paid += amount
        return {"organizations": credited, "total_paid": total_paid, "income_usd": amount}

    async def pay_business_daily_income(self) -> dict[str, int]:
        return await self._grant_organization_income(
            {"business"},
            10_000,
            kind="business_daily_income",
            description_prefix="Ежедневный доход бизнеса",
        )

    async def pay_company_weekly_income(self) -> dict[str, int]:
        return await self._grant_organization_income(
            {"company"},
            100_000,
            kind="company_weekly_income",
            description_prefix="Еженедельный доход компании",
        )

    async def pay_super_weekly_income(self) -> dict[str, int]:
        return await self._grant_organization_income(
            {"megacorp", "conglomerate"},
            200_000,
            kind="super_weekly_income",
            description_prefix="Еженедельный доход супер-организации",
        )

    async def expire_fines_to_wanted(self) -> list[dict[str, Any]]:
        now_iso = self.now_iso()
        async with self._write_lock:
            async with self.db.transaction() as conn:
                overdue_fines = await self._fetchall(
                    conn,
                    """
                    SELECT f.*, u.full_name, u.telegram_id
                    FROM fines f
                    JOIN users u ON u.telegram_id = f.target_id
                    WHERE f.status = 'active' AND f.due_at <= ? AND f.auto_wanted_created = 0
                    """,
                    (now_iso,),
                )
                created: list[dict[str, Any]] = []
                for fine in overdue_fines:
                    reason = (
                        f"Автоматический розыск: штраф #{fine['id']} не был оплачен "
                        f"в течение {self.settings.fine_deadline_days} дней."
                    )
                    cursor = await conn.execute(
                        """
                        INSERT INTO wanted_cases(
                            full_name_text, appearance, reason,
                            issuer_id, status, created_at, system_generated
                        )
                        VALUES(?, ?, ?, NULL, 'active', ?, 1)
                        """,
                        (
                            str(fine["full_name"]),
                            "Описание не указано системой",
                            reason,
                            now_iso,
                        ),
                    )
                    wanted_id = int(cursor.lastrowid)
                    await conn.execute(
                        """
                        UPDATE fines
                        SET status = 'overdue', auto_wanted_created = 1
                        WHERE id = ?
                        """,
                        (int(fine["id"]),),
                    )
                    created.append(
                        {
                            "id": wanted_id,
                            "full_name_text": str(fine["full_name"]),
                            "appearance": "Описание не указано системой",
                            "reason": reason,
                        }
                    )
                return created

    async def should_run_weekly_tax(self, now: datetime) -> bool:
        if now.weekday() != 6:
            return False
        if (now.hour, now.minute) < (self.settings.weekly_tax_hour, self.settings.weekly_tax_minute):
            return False
        last_run = await self.get_meta("last_weekly_tax_run", "")
        return last_run != now.date().isoformat()

    async def mark_weekly_tax_run(self, now: datetime) -> None:
        await self.set_meta("last_weekly_tax_run", now.date().isoformat())

    async def should_run_salary_slot(self, slot_index: int, now: datetime) -> bool:
        try:
            slot_hour = self.settings.salary_hours[slot_index]
        except IndexError:
            return False
        if (now.hour, now.minute) < (slot_hour, self.settings.salary_minute):
            return False
        last_run = await self.get_meta(f"last_salary_slot_{slot_index}", "")
        return last_run != now.date().isoformat()

    async def mark_salary_slot_run(self, slot_index: int, now: datetime) -> None:
        await self.set_meta(f"last_salary_slot_{slot_index}", now.date().isoformat())

    async def should_run_business_income(self, now: datetime) -> bool:
        business_hour = self.settings.salary_hours[0] if self.settings.salary_hours else 9
        if (now.hour, now.minute) < (business_hour, self.settings.salary_minute):
            return False
        last_run = await self.get_meta("last_business_income_run", "")
        return last_run != now.date().isoformat()

    async def mark_business_income_run(self, now: datetime) -> None:
        await self.set_meta("last_business_income_run", now.date().isoformat())

    async def should_run_company_income(self, now: datetime) -> bool:
        if now.weekday() != 6:
            return False
        if (now.hour, now.minute) < (self.settings.weekly_tax_hour, self.settings.weekly_tax_minute):
            return False
        last_run = await self.get_meta("last_company_income_run", "")
        return last_run != now.date().isoformat()

    async def mark_company_income_run(self, now: datetime) -> None:
        await self.set_meta("last_company_income_run", now.date().isoformat())

    async def should_run_super_income(self, now: datetime) -> bool:
        if now.weekday() != 6:
            return False
        if (now.hour, now.minute) < (self.settings.weekly_tax_hour, self.settings.weekly_tax_minute):
            return False
        last_run = await self.get_meta("last_super_income_run", "")
        return last_run != now.date().isoformat()

    async def mark_super_income_run(self, now: datetime) -> None:
        await self.set_meta("last_super_income_run", now.date().isoformat())

    async def should_run_fine_scan(self, now: datetime) -> bool:
        marker = now.strftime("%Y-%m-%d %H")
        last_run = await self.get_meta("last_fine_scan_hour", "")
        return last_run != marker

    async def mark_fine_scan_run(self, now: datetime) -> None:
        await self.set_meta("last_fine_scan_hour", now.strftime("%Y-%m-%d %H"))

    async def render_dispatch_fine_notice(self, fine: dict[str, Any], issuer: dict[str, Any], target: dict[str, Any]) -> str:
        return (
            "<b>Диспетчер 911</b>\n"
            "Принят новый инцидент по линии финансового контроля.\n\n"
            f"Нарушитель: {user_link(target)}\n"
            f"Сумма: <b>{format_money(int(fine['amount_usd']), 'usd')}</b>\n"
            f"Причина: {fine['reason']}\n"
            f"Оформил: {user_link(issuer)}\n"
            f"Срок оплаты: до {fine['due_at'][:16].replace('T', ' ')}"
        )

    async def render_dispatch_wanted_notice(
        self,
        wanted: dict[str, Any],
        issuer: dict[str, Any] | None = None,
        issuer_name: str | None = None,
    ) -> str:
        if issuer is not None:
            issuer_name = user_link(issuer)
        author_line = "Система Montana Safety Net" if not issuer_name else issuer_name
        return (
            "<b>Диспетчер штата Монтана</b>\n"
            "Внимание всем постам и экипажам: зарегистрирован новый розыск.\n\n"
            f"ФИО: <b>{wanted['full_name_text']}</b>\n"
            f"Приметы: {wanted['appearance']}\n"
            f"Причина: {wanted['reason']}\n"
            f"Источник: {author_line}"
        )
