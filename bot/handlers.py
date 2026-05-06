"""Telegram handlers for the Montana economy bot."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, ErrorEvent, Message

from bot.keyboards import (
    balance_keyboard,
    callback_owner,
    fines_keyboard,
    history_keyboard,
    inventory_keyboard,
    invites_keyboard,
    wanteds_keyboard,
)
from bot.services import BUSINESS_DIRECTIONS, EconomyService, ORG_CONFIG, Page, ServiceError
from bot.utils import (
    format_elapsed,
    format_money,
    format_role,
    join_lines,
    normalize_currency,
    parse_command_args,
    parse_positive_int,
    split_pipe_sections,
    user_link,
)


HELP_TEXT = """
<b>Montana Economy Bot</b>

Команды для жителей штата:
/balance - кошелёк, штрафы и последние движения
/pay [reply/@/id] [сумма] - перевод игроку
/check [reply/@/id] [сумма] [причина] - создать чек
/accept [id] - получить чек
/top - топ игроков по USD
/stats - сводка по богатству штата
/inventory - ваш инвентарь
/transfer [reply/@/id] [предмет] [кол-во] - передать предмет
/refuel [проценты] - заправить транспорт за USD
/treasuryusa - состояние казны штата
/donate [сумма] - пожертвовать в казну
/wanteds - открытый список розыска
/market - торговая площадка
/sell [предмет] | [кол-во] | [цена] | [описание] - выставить продажу
/buy [номер] [кол-во] - купить товар с площадки
/hire [текст] - опубликовать поиск сотрудника
/work [текст] - опубликовать поиск работы
/invest [название организации] [сумма] - вложить деньги в капитал организации
/buisnescreate [направление] | [название] | [описание] | [капитал] - открыть бизнес
/companycreate [направление] | [название] | [описание] | [капитал] - открыть компанию
/supercreate [тип] | [название] | [описание] | [направление] | [капитал] - открыть супер-организацию

Бизнесы:
/buisnespanel - панель владельца бизнеса
/buisnestaff - список сотрудников бизнеса
/buisnesaddstaff [reply/@/id] - пригласить сотрудника
/buisneslaries [сумма] - зарплата сотрудников бизнеса
/buisnesadd [сумма] - пополнить капитал бизнеса
/buisnesdel - закрыть бизнес
/buisnescreaterole [название] - создать роль в бизнесе
/buisnesroleset [reply/@/id] [роль] - назначить роль в бизнесе

Компании:
/companypanel - панель владельца компании
/companystaff - список сотрудников компании
/companyaddstaff [reply/@/id] - пригласить сотрудника
/companylaries [сумма] - зарплата сотрудников компании
/companyadd [сумма] - пополнить капитал компании
/companydel - закрыть компанию
/companycreaterole [название] - создать роль в компании
/companyroleset [reply/@/id] [роль] - назначить роль в компании

Супер-организации:
/superpanel - панель владельца
/superstaff - список сотрудников
/superaddstaff [reply/@/id] - пригласить сотрудника
/superlaries [сумма] - зарплата сотрудников
/superadd [сумма] - пополнить капитал
/superdel - закрыть организацию
/supercreaterole [название] - создать роль
/superroleset [reply/@/id] [роль] - назначить роль

В группах можно отвечать на сообщение человека и не писать его @username.
""".strip()


ADMIN_PANEL_TEXT = """
<b>Админ-панель</b>

/adminpanel - открыть эту панель
/add [reply/@/id] [сумма] [валюта] - добавить деньги
/remove [reply/@/id] [сумма] [валюта] - убрать деньги
/additem [reply/@/id] [предмет] [кол-во] - выдать предмет
/removeitem [reply/@/id] [предмет] [кол-во] - изъять предмет
/setfinechat - привязать топик для уведомлений о штрафах
/setwantedchat - привязать топик для уведомлений о розыске
/setvakchat - привязать топик для торговой площадки и вакансий
""".strip()


OWNER_PANEL_TEXT = """
<b>Панель владельца</b>

/ownerpanel - открыть эту панель
/rank [reply/@/id] - выдать администратора
/unrank [reply/@/id] - снять администратора
/setpresident [reply/@/id] - назначить президента
/addpresident [reply/@/id] - назначить президента
/removepresident - снять президента
/allowmega [reply/@/id] - разрешить мега-корпорацию
/allowconglomerate [reply/@/id] - разрешить глобальный конгломерат

Основной владелец бота: <code>8376083253</code>
""".strip()


PRESIDENT_PANEL_TEXT = """
<b>Панель президента</b>

/presidentpanel - открыть эту панель
/settax [число] [число] [число] - задать 1-3 налога, суммарно до 700 USD
/addgos [reply/@/id] - добавить человека в госструктуры
/delgos [reply/@/id] - убрать человека из госструктур
/setgossalaries [число] - установить общую зарплату госслужащим
/withdraw [reply/@/id] [сумма] - выплата из казны

Налоги списываются автоматически каждое воскресенье.
""".strip()


POLICE_PANEL_TEXT = """
<b>Панель госструктур</b>

/policepanep - открыть эту панель
/fine [reply/@/id] [сумма] [причина] - выписать штраф
/fines - список штрафов
/unfine [reply/@/id] - убрать уже оплаченные штрафы из активного списка
/wanted [ФИО] | [приметы] | [причина] - оформить розыск
/wanteds - список активных розысков
/unwanted [id] - снять розыск
""".strip()


BUSINESS_DIRECTIONS_TEXT = ", ".join(sorted(direction.title() for direction in BUSINESS_DIRECTIONS))


MARKET_HELP_TEXT = """
<b>Торговая площадка</b>

/market - список активных продаж
/sell [предмет] | [кол-во] | [цена] | [описание] - выставить товар
/buy [номер] [кол-во] - купить товар
/hire [текст] - объявление #ИщюСотрудника
/work [текст] - объявление #ИщюРаботу
""".strip()

BUSINESS_TYPES = {"business"}
COMPANY_TYPES = {"company"}
SUPER_TYPES = {"megacorp", "conglomerate"}


def build_router(services: EconomyService) -> Router:
    router = Router(name="montana-handlers")
    pending_sticker_ids: set[int] = set()

    async def actor_from_message(message: Message) -> dict:
        if message.from_user is None:
            raise ServiceError("Не удалось определить отправителя сообщения.")
        return await services.ensure_user(message.from_user)

    async def actor_from_callback(callback: CallbackQuery) -> dict:
        if callback.from_user is None:
            raise ServiceError("Не удалось определить отправителя нажатия.")
        return await services.ensure_user(callback.from_user)

    def reply_user(message: Message):
        def usable(candidate):
            return candidate is not None and not getattr(candidate, "is_bot", False)

        reply_message = getattr(message, "reply_to_message", None)
        if reply_message is not None:
            reply_from_user = getattr(reply_message, "from_user", None)
            if usable(reply_from_user):
                return reply_from_user

            reply_forward_from = getattr(reply_message, "forward_from", None)
            if usable(reply_forward_from):
                return reply_forward_from

            reply_forward_origin = getattr(reply_message, "forward_origin", None)
            reply_sender_user = getattr(reply_forward_origin, "sender_user", None)
            if usable(reply_sender_user):
                return reply_sender_user

        external_reply = getattr(message, "external_reply", None)
        if external_reply is not None:
            origin = getattr(external_reply, "origin", None)
            sender_user = getattr(origin, "sender_user", None)
            if usable(sender_user):
                return sender_user
        return None

    def has_reply_context(message: Message) -> bool:
        return (
            getattr(message, "reply_to_message", None) is not None
            or getattr(message, "external_reply", None) is not None
            or getattr(message, "quote", None) is not None
            or getattr(message, "reply_to_story", None) is not None
        )

    def reply_target_unavailable_error() -> ServiceError:
        return ServiceError(
            "Бот не смог определить автора reply. В группах это обычно происходит, "
            "когда у бота включён Privacy Mode в BotFather. "
            "Отключите Privacy Mode или используйте @username / ID."
        )

    def is_reference_token(token: str) -> bool:
        cleaned = token.strip()
        return (cleaned.startswith("@") and len(cleaned) > 1) or cleaned.isdigit()

    async def resolve_target_by_token(token: str) -> dict:
        return await services.resolve_reference(token)

    async def maybe_resolve_target_by_token(token: str) -> dict | None:
        try:
            return await services.resolve_reference(token)
        except ServiceError:
            return None

    def parse_optional_positive_int(raw: str) -> int | None:
        try:
            return parse_positive_int(raw)
        except ValueError:
            return None

    async def resolve_target(message: Message, args: list[str], target_index: int = 0) -> dict:
        reply = reply_user(message)

        if len(args) > target_index and is_reference_token(args[target_index]):
            return await resolve_target_by_token(args[target_index])

        if args and is_reference_token(args[-1]):
            return await resolve_target_by_token(args[-1])

        if reply is not None:
            return await services.resolve_reference(reply_user=reply)

        reference = args[target_index] if len(args) > target_index else None
        if reference is None:
            raise ServiceError("Данные заполнены неправильно. Укажите пользователя через reply, @username или ID.")
        return await services.resolve_reference(reference)

    async def parse_target_only(message: Message, args: list[str], example: str) -> dict:
        if args:
            if len(args) != 1:
                raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")
            if is_reference_token(args[0]):
                return await resolve_target_by_token(args[0])
            maybe_target = await maybe_resolve_target_by_token(args[0])
            if maybe_target is not None:
                return maybe_target
            raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")

        replied_user = reply_user(message)
        if replied_user is None:
            if has_reply_context(message):
                raise reply_target_unavailable_error()
            raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")
        return await services.resolve_reference(reply_user=replied_user)

    async def parse_target_amount_currency(
        message: Message,
        args: list[str],
        example: str,
        *,
        allow_self_single_amount: bool = False,
        allow_target_last: bool = True,
    ) -> tuple[dict, int, str]:
        replied_user = reply_user(message)
        first_amount = parse_optional_positive_int(args[0]) if args else None
        second_amount = parse_optional_positive_int(args[1]) if len(args) > 1 else None

        if not args:
            raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")

        if is_reference_token(args[0]):
            if len(args) not in {2, 3}:
                raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")
            target = await resolve_target_by_token(args[0])
            amount = parse_positive_int(args[1])
            currency = normalize_currency(args[2] if len(args) > 2 else "usd")
            return target, amount, currency

        if allow_target_last and len(args) >= 2 and is_reference_token(args[-1]):
            if len(args) not in {2, 3}:
                raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")
            target = await resolve_target_by_token(args[-1])
            amount = parse_positive_int(args[0])
            currency = normalize_currency(args[1] if len(args) == 3 else "usd")
            return target, amount, currency

        if len(args) in {2, 3} and second_amount is not None:
            maybe_target = await maybe_resolve_target_by_token(args[0])
            if maybe_target is not None:
                currency = normalize_currency(args[2] if len(args) > 2 else "usd")
                return maybe_target, second_amount, currency

        if allow_target_last and len(args) in {2, 3} and first_amount is not None:
            maybe_target = await maybe_resolve_target_by_token(args[-1])
            if maybe_target is not None:
                currency = normalize_currency(args[1] if len(args) == 3 else "usd")
                return maybe_target, first_amount, currency

        if replied_user is not None:
            if len(args) not in {1, 2}:
                raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")
            target = await services.resolve_reference(reply_user=replied_user)
            amount = parse_positive_int(args[0])
            currency = normalize_currency(args[1] if len(args) > 1 else "usd")
            return target, amount, currency

        if allow_self_single_amount and len(args) in {1, 2}:
            amount = parse_positive_int(args[0])
            currency = normalize_currency(args[1] if len(args) > 1 else "usd")
            return await actor_from_message(message), amount, currency

        if has_reply_context(message):
            raise reply_target_unavailable_error()
        raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")

    async def parse_target_amount_reason(
        message: Message,
        args: list[str],
        example: str,
    ) -> tuple[dict, int, str]:
        replied_user = reply_user(message)
        second_amount = parse_optional_positive_int(args[1]) if len(args) > 1 else None

        if not args:
            raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")

        if is_reference_token(args[0]):
            if len(args) < 3:
                raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")
            target = await resolve_target_by_token(args[0])
            amount = parse_positive_int(args[1])
            reason = " ".join(args[2:]).strip()
        elif len(args) >= 3 and is_reference_token(args[-1]):
            target = await resolve_target_by_token(args[-1])
            amount = parse_positive_int(args[0])
            reason = " ".join(args[1:-1]).strip()
        elif len(args) >= 3 and second_amount is not None:
            maybe_target = await maybe_resolve_target_by_token(args[0])
            if maybe_target is not None:
                target = maybe_target
                amount = second_amount
                reason = " ".join(args[2:]).strip()
            else:
                raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")
        elif replied_user is not None:
            if len(args) < 2:
                raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")
            target = await services.resolve_reference(reply_user=replied_user)
            amount = parse_positive_int(args[0])
            reason = " ".join(args[1:]).strip()
        else:
            if has_reply_context(message):
                raise reply_target_unavailable_error()
            raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")

        if not reason:
            raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")
        return target, amount, reason

    async def parse_target_amount_currency_reason(
        message: Message,
        args: list[str],
        example: str,
    ) -> tuple[dict, int, str, str]:
        replied_user = reply_user(message)
        second_amount = parse_optional_positive_int(args[1]) if len(args) > 1 else None

        if not args:
            raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")

        if is_reference_token(args[0]):
            if len(args) < 2:
                raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")
            target = await resolve_target_by_token(args[0])
            amount = parse_positive_int(args[1])
            payload = args[2:]
        elif len(args) >= 2 and is_reference_token(args[-1]):
            target = await resolve_target_by_token(args[-1])
            amount = parse_positive_int(args[0])
            payload = args[1:-1]
        elif len(args) >= 2 and second_amount is not None:
            maybe_target = await maybe_resolve_target_by_token(args[0])
            if maybe_target is not None:
                target = maybe_target
                amount = second_amount
                payload = args[2:]
            else:
                raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")
        elif replied_user is not None:
            target = await services.resolve_reference(reply_user=replied_user)
            amount = parse_positive_int(args[0])
            payload = args[1:]
        else:
            if has_reply_context(message):
                raise reply_target_unavailable_error()
            raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")

        currency = "usd"
        if payload:
            try:
                currency = normalize_currency(payload[0])
                payload = payload[1:]
            except ValueError:
                currency = "usd"
        reason = " ".join(payload).strip() or "Без пояснения"
        return target, amount, currency, reason

    async def parse_target_item_quantity(
        message: Message,
        args: list[str],
        example: str,
    ) -> tuple[dict, str, int]:
        replied_user = reply_user(message)

        if not args:
            raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")

        if is_reference_token(args[0]):
            if len(args) < 3:
                raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")
            target = await resolve_target_by_token(args[0])
            item_name, quantity = item_name_and_quantity(args[1:])
            return target, item_name, quantity

        if len(args) >= 3 and is_reference_token(args[-1]):
            target = await resolve_target_by_token(args[-1])
            item_name, quantity = item_name_and_quantity(args[:-1])
            return target, item_name, quantity

        if replied_user is None and len(args) >= 3:
            maybe_target = await maybe_resolve_target_by_token(args[0])
            if maybe_target is not None:
                item_name, quantity = item_name_and_quantity(args[1:])
                return maybe_target, item_name, quantity

        if replied_user is not None:
            target = await services.resolve_reference(reply_user=replied_user)
            item_name, quantity = item_name_and_quantity(args)
            return target, item_name, quantity

        if has_reply_context(message):
            raise reply_target_unavailable_error()
        raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")

    async def parse_target_and_text(
        message: Message,
        args: list[str],
        example: str,
    ) -> tuple[dict, str]:
        replied_user = reply_user(message)

        if replied_user is not None:
            text = " ".join(args).strip()
            if not text:
                raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")
            target = await services.resolve_reference(reply_user=replied_user)
            return target, text

        if len(args) >= 2 and is_reference_token(args[0]):
            target = await resolve_target_by_token(args[0])
            text = " ".join(args[1:]).strip()
            if not text:
                raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")
            return target, text

        if len(args) >= 2 and is_reference_token(args[-1]):
            target = await resolve_target_by_token(args[-1])
            text = " ".join(args[:-1]).strip()
            if not text:
                raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")
            return target, text

        if replied_user is None and len(args) >= 2:
            maybe_target = await maybe_resolve_target_by_token(args[0])
            if maybe_target is not None:
                text = " ".join(args[1:]).strip()
                if not text:
                    raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")
                return maybe_target, text

        if has_reply_context(message):
            raise reply_target_unavailable_error()
        raise ServiceError(f"Данные заполнены неправильно.\nПример: {example}")

    def payload_after_command(message: Message) -> str:
        return (message.text or "").split(maxsplit=1)[1] if message.text and " " in message.text else ""

    def item_name_and_quantity(parts: list[str]) -> tuple[str, int]:
        if len(parts) < 2:
            raise ServiceError("Нужно указать название предмета и количество.")
        quantity = parse_positive_int(parts[-1])
        name = " ".join(parts[:-1]).strip()
        if not name:
            raise ServiceError("Нужно указать название предмета.")
        return name, quantity

    def strip_reply_reference(args: list[str]) -> list[str]:
        if args and is_reference_token(args[0]):
            return args[1:]
        return args

    async def respond_panel(
        message: Message,
        text: str,
        *,
        edit: bool = False,
        reply_markup=None,
    ) -> None:
        if edit:
            try:
                await message.edit_text(text, reply_markup=reply_markup)
                return
            except TelegramBadRequest as exc:
                lowered = str(exc).lower()
                if "message is not modified" in lowered:
                    return
                if "there is no text in the message to edit" not in lowered:
                    raise
        await message.answer(text, reply_markup=reply_markup)

    async def render_balance(message: Message, actor: dict, subject: dict, *, edit: bool = False) -> None:
        overview = await services.get_balance_overview(subject["telegram_id"])
        user = overview["user"]
        lines = [
            f"<b>Личный кабинет штата {services.settings.state_name}</b>",
            "",
            f"Профиль: {user_link(user)}",
            f"Роль: <b>{format_role(user['role'])}</b>",
            f"Статус госслужбы: <b>{'Да' if int(user['is_government']) else 'Нет'}</b>",
            f"USD: <b>{format_money(int(user['usd_balance']), 'usd')}</b>",
            f"Топливо: <b>{int(user['car_fuel'])}%</b>",
            f"Активные штрафы: <b>{overview['fine_count']}</b>",
        ]
        if actor["telegram_id"] != subject["telegram_id"]:
            lines.append("Режим просмотра: <b>чужой профиль</b>")
        organization = overview.get("organization")
        if organization is not None:
            lines.append(
                f"Организация: <b>{organization['name']}</b> ({organization['type_label']})"
            )
        if actor["telegram_id"] == subject["telegram_id"]:
            lines.append(f"Приглашения в организации: <b>{overview['pending_invites']}</b>")
        if overview["recent"]:
            lines.extend(["", "<b>Последние операции</b>"])
            for row in overview["recent"]:
                lines.append(
                    f"#{row['id']} - {row['description']} - {format_money(int(row['amount']), row['currency'])}"
                )
        await respond_panel(
            message,
            join_lines(lines),
            edit=edit,
            reply_markup=balance_keyboard(
                actor["telegram_id"],
                subject["telegram_id"],
                overview["fine_count"] > 0,
                actor["telegram_id"] == subject["telegram_id"] and overview["pending_invites"] > 0,
            ),
        )

    async def render_inventory(message: Message, actor: dict, subject: dict, *, edit: bool = False) -> None:
        user = await services.get_user(subject["telegram_id"])
        items = await services.list_inventory(subject["telegram_id"])
        lines = [
            "<b>Инвентарь</b>",
            "",
            f"Владелец: {user_link(subject)}",
            f"Транспортное топливо: <b>{int(user['car_fuel'])}%</b>",
        ]
        if items:
            lines.extend(["", "<b>Предметы</b>"])
            for item in items:
                lines.append(f"• {item['name']} x{item['quantity']}")
        else:
            lines.extend(["", "Предметов пока нет."])
        await respond_panel(
            message,
            join_lines(lines),
            edit=edit,
            reply_markup=inventory_keyboard(actor["telegram_id"], subject["telegram_id"]),
        )

    async def render_fines_message(
        message: Message,
        actor: dict,
        page: int,
        *,
        filter_target_id: int | None,
        back_subject_id: int,
        can_pay: bool,
        edit: bool = False,
    ) -> None:
        fine_page = await services.list_fines(
            target_id=filter_target_id,
            page=page,
        )
        await respond_panel(
            message,
            render_fines_text(fine_page, services.now()),
            edit=edit,
            reply_markup=fines_keyboard(
                actor["telegram_id"],
                0 if filter_target_id is None else filter_target_id,
                back_subject_id,
                fine_page.page,
                fine_page.total_pages,
                [
                    int(item["id"])
                    for item in fine_page.items
                    if can_pay and item["status"] in {"active", "overdue"}
                ],
            ),
        )

    async def render_history_message(
        message: Message,
        actor: dict,
        subject: dict,
        page: int,
        *,
        edit: bool = False,
    ) -> None:
        page_obj = await services.list_transaction_history(subject["telegram_id"], page)
        lines = [
            f"<b>История операций</b>",
            f"Профиль: {user_link(subject)}",
            f"Страница {page_obj.page + 1}/{page_obj.total_pages}",
            "",
        ]
        if not page_obj.items:
            lines.append("Операций пока нет.")
        else:
            for row in page_obj.items:
                lines.extend(
                    [
                        f"#{row['id']} - {row['created_at'][:16].replace('T', ' ')}",
                        f"{row['description']}",
                        f"Сумма: <b>{format_money(int(row['amount']), row['currency'])}</b>",
                        "",
                    ]
                )
        await respond_panel(
            message,
            join_lines(lines),
            edit=edit,
            reply_markup=history_keyboard(actor["telegram_id"], subject["telegram_id"], page_obj.page, page_obj.total_pages),
        )

    async def render_invites_message(message: Message, actor: dict, page: int, *, edit: bool = False) -> None:
        invites = await services.list_pending_organization_invites(actor["telegram_id"])
        page = max(page, 0)
        page_size = 5
        total_pages = max((len(invites) + page_size - 1) // page_size, 1)
        page = min(page, total_pages - 1)
        chunk = invites[page * page_size : (page + 1) * page_size]
        lines = ["<b>Приглашения в организации</b>", f"Страница {page + 1}/{total_pages}", ""]
        if not chunk:
            lines.append("Новых приглашений нет.")
        else:
            for invite in chunk:
                lines.extend(
                    [
                        f"#{invite['id']} - <b>{invite['organization_name']}</b>",
                        f"Тип: {ORG_CONFIG[str(invite['org_type'])]['label']}",
                        f"Направление: {invite['direction']}",
                        f"Описание: {invite['short_description']}",
                        f"Пригласил: {invite['inviter_name']}",
                        "",
                    ]
                )
        await respond_panel(
            message,
            join_lines(lines),
            edit=edit,
            reply_markup=invites_keyboard(actor["telegram_id"], page, total_pages, [int(invite["id"]) for invite in chunk]),
        )

    def render_market_text(page_obj: Page) -> str:
        lines = ["<b>Торговая площадка</b>", f"Страница {page_obj.page + 1}/{page_obj.total_pages}", ""]
        if not page_obj.items:
            lines.append("Активных лотов пока нет.")
            return join_lines(lines)
        for post in page_obj.items:
            lines.extend(
                [
                    f"#{post['id']} - <b>{post['title']}</b>",
                    f"Продавец: {user_link({'full_name': post['owner_name'], 'telegram_id': post['owner_id']})}",
                    f"Остаток: <b>{post['remaining_quantity']}</b> из {post['quantity']}",
                    f"Цена за единицу: <b>{format_money(int(post['price_usd']), 'usd')}</b>",
                    f"Описание: {post['body']}",
                    "",
                ]
            )
        return join_lines(lines)

    def render_organization_panel_text(panel: dict[str, Any]) -> str:
        lines = [
            f"<b>{panel['type_label']}</b>",
            "",
            f"Название: <b>{panel['name']}</b>",
            f"Направление: {panel['direction']}",
            f"Описание: {panel['short_description']}",
            f"Капитал: <b>{format_money(int(panel['capital_usd']), 'usd')}</b>",
            f"Зарплата сотрудника: <b>{format_money(int(panel['payroll_usd']), 'usd')}</b>",
            f"Сотрудников: <b>{panel['staff_count']}</b>",
            f"Кастомных ролей: <b>{panel['role_count']}</b>",
            f"Ожидают приглашения: <b>{panel['pending_invites']}</b>",
        ]
        return join_lines(lines)

    def render_fines_text(page_obj: Page, now: datetime) -> str:
        lines = [f"<b>Штрафы</b>", f"Страница {page_obj.page + 1}/{page_obj.total_pages}", ""]
        if not page_obj.items:
            lines.append("Штрафов не найдено.")
            return join_lines(lines)
        for fine in page_obj.items:
            issued = datetime.fromisoformat(fine["issued_at"])
            elapsed = format_elapsed(issued, now)
            target = user_link({"full_name": fine["target_name"], "telegram_id": fine["target_id"]})
            issuer = "Система"
            if fine.get("issuer_id"):
                issuer = user_link({"full_name": fine["issuer_name"], "telegram_id": fine["issuer_id"]})
            lines.extend(
                [
                    f"#{fine['id']} - {target}",
                    f"Сумма: <b>{format_money(int(fine['amount_usd']), 'usd')}</b>",
                    f"Причина: {fine['reason']}",
                    f"Статус: <b>{fine['status']}</b>",
                    f"Оформил: {issuer}",
                    f"Прошло времени: {elapsed}",
                    "",
                ]
            )
        return join_lines(lines)

    def render_wanteds_text(page_obj: Page) -> str:
        lines = [f"<b>Розыск</b>", f"Страница {page_obj.page + 1}/{page_obj.total_pages}", ""]
        if not page_obj.items:
            lines.append("Активных розысков нет.")
            return join_lines(lines)
        for wanted in page_obj.items:
            issuer = (
                user_link({"full_name": wanted["issuer_name"], "telegram_id": wanted["issuer_id"]})
                if wanted.get("issuer_id")
                else "Система"
            )
            lines.extend(
                [
                    f"#{wanted['id']} - <b>{wanted['full_name_text']}</b>",
                    f"Приметы: {wanted['appearance']}",
                    f"Причина: {wanted['reason']}",
                    f"Источник: {issuer}",
                    "",
                ]
            )
        return join_lines(lines)

    async def render_wanteds_message(message: Message, actor: dict, page: int, *, edit: bool = False) -> None:
        page_obj = await services.list_wanteds(page)
        await respond_panel(
            message,
            render_wanteds_text(page_obj),
            edit=edit,
            reply_markup=wanteds_keyboard(actor["telegram_id"], page_obj.page, page_obj.total_pages),
        )

    @router.error()
    async def on_error(event: ErrorEvent) -> None:
        exc = event.exception
        if isinstance(exc, TelegramRetryAfter):
            return
        text = str(exc) if isinstance(exc, (ServiceError, ValueError)) else "Что-то пошло не так. Попробуйте ещё раз."
        if event.update.message:
            try:
                await event.update.message.answer(text)
            except (TelegramRetryAfter, TelegramAPIError):
                return
            return
        if event.update.callback_query:
            try:
                await event.update.callback_query.answer(text, show_alert=True)
            except (TelegramRetryAfter, TelegramAPIError):
                return

    @router.message(CommandStart())
    async def start_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        await message.answer(
            join_lines(
                [
                    f"<b>Добро пожаловать в систему экономики штата {services.settings.state_name}</b>",
                    "",
                    f"Здравствуйте, {user_link(actor)}.",
                    "Здесь собраны личные финансы, казна, штрафы, государственные выплаты и розыск.",
                    "Начните с /balance или /help.",
                ]
            )
        )

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await actor_from_message(message)
        await message.answer(
            HELP_TEXT
            + "\n/id [reply/@/id] - показать ID игрока"
            + "\n/stikid - узнать ID первого стикера в личке с ботом"
        )

    @router.message(Command("id"))
    async def id_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)

        if not args and reply_user(message) is None:
            await message.answer(f"Ваш ID: <code>{actor['telegram_id']}</code>\nПрофиль: {user_link(actor)}")
            return

        if args and len(args) == 1 and args[0].strip().isdigit() and reply_user(message) is None:
            raw_id = int(args[0].strip())
            known_user = await services.get_user(raw_id)
            if known_user is None:
                await message.answer(f"Указанный ID: <code>{raw_id}</code>")
                return

        target = await parse_target_only(message, args, "/id @player или reply + /id")
        await message.answer(f"ID профиля {user_link(target)}: <code>{target['telegram_id']}</code>")
    @router.message(Command("stikid"))
    async def stikid_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        if message.chat.type != "private":
            raise ServiceError("Команда /stikid работает только в личных сообщениях с ботом.")
        pending_sticker_ids.add(actor["telegram_id"])
        await message.answer("Отправьте один стикер, и я покажу его ID.")

    @router.message(F.sticker)
    async def sticker_debug_handler(message: Message) -> None:
        if message.chat.type != "private" or message.from_user is None:
            return
        if message.from_user.id not in pending_sticker_ids:
            return
        pending_sticker_ids.discard(message.from_user.id)
        sticker = message.sticker
        if sticker is None:
            return
        lines = [
            "<b>Данные стикера</b>",
            f"ID: <code>{sticker.file_id}</code>",
            f"Уникальный ID: <code>{sticker.file_unique_id}</code>",
        ]
        if sticker.set_name:
            lines.append(f"Набор: <code>{sticker.set_name}</code>")
        await message.answer(join_lines(lines))

    @router.message(Command("balance"))
    async def balance_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        subject = actor
        reply_target = reply_user(message)
        if args or (reply_target is not None and actor["role"] in {"admin", "owner"}):
            if actor["role"] not in {"admin", "owner"}:
                raise ServiceError("Просматривать чужие профили могут только администраторы и владелец.")
            subject = await parse_target_only(message, args, "/balance @player или reply + /balance")
        if actor["role"] not in {"admin", "owner"}:
            subject = actor
        await render_balance(message, actor, subject)

    @router.message(Command("inventory"))
    async def inventory_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        subject = actor
        reply_target = reply_user(message)
        if args or (reply_target is not None and actor["role"] in {"admin", "owner"}):
            if actor["role"] not in {"admin", "owner"}:
                raise ServiceError("Просматривать чужой инвентарь могут только администраторы и владелец.")
            subject = await parse_target_only(message, args, "/inventory @player или reply + /inventory")
        if actor["role"] not in {"admin", "owner"}:
            subject = actor
        await render_inventory(message, actor, subject)

    @router.message(Command("pay"))
    async def pay_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        target, amount, currency = await parse_target_amount_currency(
            message,
            args,
            "/pay @player 150 или /pay 150 @player",
        )
        await services.pay(actor, target, amount, currency)
        await message.answer(
            f"Перевод для {user_link(target)} выполнен: <b>{format_money(amount, currency)}</b>."
        )
    @router.message(Command("check"))
    async def check_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        target, amount, currency, reason = await parse_target_amount_currency_reason(
            message,
            args,
            "/check @player 200 Компенсация или /check 200 Компенсация @player",
        )
        check_id = await services.create_check(actor, target, amount, currency, reason)
        await message.answer(
            f"Чек <b>#{check_id}</b> создан для {user_link(target)} на сумму <b>{format_money(amount, currency)}</b>."
        )
    @router.message(Command("accept"))
    async def accept_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        if not args:
            pending = await services.list_pending_checks_for_user(actor["telegram_id"])
            if not pending:
                await message.answer("На ваше имя пока нет активных чеков.")
                return
            lines = ["<b>Ожидающие чеки</b>", ""]
            for item in pending:
                lines.append(
                    f"#{item['id']} - "
                    f"{user_link({'full_name': item['sender_name'], 'telegram_id': item['sender_telegram_id']})} - "
                    f"{format_money(int(item['amount']), item['currency'])}"
                )
            await message.answer(join_lines(lines))
            return
        check_id = parse_positive_int(args[0])
        check = await services.accept_check(actor, check_id)
        await message.answer(
            f"Чек #{check_id} погашен. На баланс зачислено <b>{format_money(int(check['amount']), check['currency'])}</b>."
        )

    @router.message(Command("top"))
    @router.message(Command("topusd"))
    async def top_usd_handler(message: Message) -> None:
        await actor_from_message(message)
        top = await services.get_top("usd")
        lines = ["<b>Топ игроков штата по USD</b>", ""]
        for index, player in enumerate(top, start=1):
            lines.append(
                f"{index}. {user_link(player)} - <b>{format_money(int(player['balance']), 'usd')}</b>"
            )
        await message.answer(join_lines(lines))

    @router.message(Command("stats"))
    async def stats_handler(message: Message) -> None:
        await actor_from_message(message)
        stats = await services.get_stats()
        richest = stats["richest"]
        lines = [
            "<b>Статистика богатейших игроков</b>",
            "",
            f"Игроков в системе: <b>{stats['players']}</b>",
            f"Всего USD: <b>{format_money(stats['usd_total'], 'usd')}</b>",
            f"Казна: <b>{format_money(stats['treasury_usd'], 'usd')}</b>",
            f"Общий капитал системы: <b>{format_money(stats['usd_equivalent_total'], 'usd')}</b>",
        ]
        if richest:
            lines.append(f"Самый богатый по USD: {user_link(richest)}")
        await message.answer(join_lines(lines))

    @router.message(Command("transfer"))
    async def transfer_item_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        target, item_name, quantity = await parse_target_item_quantity(
            message,
            args,
            "/transfer @player Аптечка 2 или /transfer Аптечка 2 @player",
        )
        await services.inventory_transfer(actor, target, item_name, quantity)
        await message.answer(f"Предмет <b>{item_name}</b> x{quantity} передан игроку {user_link(target)}.")
    @router.message(Command("refuel"))
    async def refuel_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        amount = parse_positive_int(args[0]) if args else None
        result = await services.refuel(actor, amount)
        await message.answer(
            f"Транспорт заправлен на <b>{result['fuel_added']}%</b>. Списано <b>{format_money(result['cost_usd'], 'usd')}</b>."
        )

    @router.message(Command("treasuryusa"))
    async def treasury_handler(message: Message) -> None:
        await actor_from_message(message)
        snapshot = await services.treasury_snapshot()
        tax_line = ", ".join(format_money(amount, "usd") for amount in snapshot["taxes"]) or "налогов нет"
        await message.answer(
            join_lines(
                [
                    f"<b>Казна штата {services.settings.state_name}</b>",
                    "",
                    f"Баланс: <b>{format_money(snapshot['treasury_usd'], 'usd')}</b>",
                    f"Сотрудников госструктур: <b>{snapshot['staff_count']}</b>",
                    f"Зарплата госслужащего: <b>{format_money(snapshot['gov_salary_usd'], 'usd')}</b>",
                    f"Еженедельные налоги: <b>{tax_line}</b>",
                ]
            )
        )

    @router.message(Command("donate"))
    async def donate_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        if not args:
            raise ServiceError("Пример: /donate 500")
        treasury = await services.donate_to_treasury(actor, parse_positive_int(args[0]))
        await message.answer(f"Казна пополнена. Новый баланс: <b>{format_money(treasury, 'usd')}</b>.")

    @router.message(Command("withdraw"))
    async def withdraw_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        target, amount, _ = await parse_target_amount_currency(
            message,
            args,
            "/withdraw 500 или /withdraw @player 500 или /withdraw 500 @player",
            allow_self_single_amount=True,
        )
        treasury = await services.treasury_withdraw(actor, target, amount)
        await message.answer(
            f"Из казны выдано <b>{format_money(amount, 'usd')}</b> для {user_link(target)}. Остаток казны: <b>{format_money(treasury, 'usd')}</b>."
        )
    @router.message(Command("rank"))
    async def rank_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        target = await parse_target_only(message, parse_command_args(message.text), "/rank @player или reply + /rank")
        updated = await services.set_role(actor, target, "admin")
        await message.answer(f"{user_link(updated)} назначен администратором.")
    @router.message(Command("unrank"))
    async def unrank_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        target = await parse_target_only(message, parse_command_args(message.text), "/unrank @player или reply + /unrank")
        updated = await services.set_role(actor, target, "citizen")
        await message.answer(f"Права администратора сняты у {user_link(updated)}.")
    @router.message(Command("setpresident"))
    @router.message(Command("addpresident"))
    async def set_president_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        target = await parse_target_only(
            message,
            parse_command_args(message.text),
            "/setpresident @player или reply + /setpresident",
        )
        updated = await services.set_role(actor, target, "president")
        await message.answer(f"{user_link(updated)} назначен президентом штата.")
    @router.message(Command("removepresident"))
    async def remove_president_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        count = await services.remove_president(actor)
        await message.answer(f"Президентская роль снята у {count} профилей.")

    @router.message(Command("add"))
    async def add_money_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        target, amount, currency = await parse_target_amount_currency(
            message,
            args,
            "/add @player 500 usd или /add 500 usd @player",
        )
        await services.adjust_money(actor, target, amount, currency, add=True)
        await message.answer(f"{user_link(target)} начислено <b>{format_money(amount, currency)}</b>.")
    @router.message(Command("remove"))
    async def remove_money_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        target, amount, currency = await parse_target_amount_currency(
            message,
            args,
            "/remove @player 500 usd или /remove 500 usd @player",
        )
        await services.adjust_money(actor, target, amount, currency, add=False)
        await message.answer(f"У {user_link(target)} списано <b>{format_money(amount, currency)}</b>.")
    @router.message(Command("additem"))
    async def add_item_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        target, item_name, quantity = await parse_target_item_quantity(
            message,
            args,
            "/additem @player Канистра 2 или /additem Канистра 2 @player",
        )
        await services.add_item(actor, target, item_name, quantity)
        await message.answer(f"Игроку {user_link(target)} выдан предмет <b>{item_name}</b> x{quantity}.")
    @router.message(Command("removeitem"))
    async def remove_item_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        target, item_name, quantity = await parse_target_item_quantity(
            message,
            args,
            "/removeitem @player Канистра 1 или /removeitem Канистра 1 @player",
        )
        await services.remove_item(actor, target, item_name, quantity)
        await message.answer(f"У {user_link(target)} изъят предмет <b>{item_name}</b> x{quantity}.")
    @router.message(Command("settax"))
    async def set_tax_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        if not args:
            raise ServiceError("Пример: /settax 200 150 50")
        amounts = [parse_positive_int(value) for value in args]
        configured = await services.set_taxes(actor, amounts)
        tax_line = ", ".join(format_money(value, "usd") for value in configured)
        await message.answer(f"Налоги обновлены: <b>{tax_line}</b>.")

    @router.message(Command("addgos"))
    async def add_gos_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        target = await parse_target_only(message, parse_command_args(message.text), "/addgos @player или reply + /addgos")
        updated = await services.set_government_status(actor, target, True)
        await message.answer(f"{user_link(updated)} добавлен в государственные структуры.")
    @router.message(Command("delgos"))
    async def del_gos_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        target = await parse_target_only(message, parse_command_args(message.text), "/delgos @player или reply + /delgos")
        updated = await services.set_government_status(actor, target, False)
        await message.answer(f"{user_link(updated)} выведен из государственных структур.")
    @router.message(Command("setgossalaries"))
    async def set_gov_salary_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        if not args:
            raise ServiceError("Пример: /setgossalaries 400")
        salary = await services.set_government_salary(actor, parse_positive_int(args[0]))
        await message.answer(f"Общая зарплата госслужащих установлена: <b>{format_money(salary, 'usd')}</b>.")

    @router.message(Command("adminpanel"))
    async def admin_panel_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        services._ensure_admin(actor)
        await message.answer(ADMIN_PANEL_TEXT)

    @router.message(Command("ownerpanel"))
    async def owner_panel_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        services._ensure_owner(actor)
        await message.answer(OWNER_PANEL_TEXT)

    @router.message(Command("presidentpanel"))
    async def president_panel_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        services._ensure_president(actor)
        await message.answer(PRESIDENT_PANEL_TEXT)

    @router.message(Command("policepanep"))
    @router.message(Command("policepanel"))
    async def police_panel_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        services._ensure_official(actor)
        await message.answer(POLICE_PANEL_TEXT)

    @router.message(Command("fine"))
    async def fine_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        target, amount, reason = await parse_target_amount_reason(
            message,
            args,
            "/fine @player 450 Причина или /fine 450 Причина @player",
        )
        fine = await services.issue_fine(actor, target, amount, reason)
        notice = await services.render_dispatch_fine_notice(fine, actor, target)
        await services.send_topic_notice(message.bot, "fine", notice)
        await services.notify_government_staff(message.bot, notice)
        await services.maybe_send_private(
            message.bot,
            target["telegram_id"],
            f"Вам выписан штраф #{fine['id']} на сумму {format_money(amount, 'usd')}.\nПричина: {reason}",
        )
        await message.answer(f"Штраф #{fine['id']} оформлен для {user_link(target)}.")
    @router.message(Command("fines"))
    async def fines_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        can_view_all = actor["role"] in {"owner", "admin", "president"} or int(actor["is_government"])
        await render_fines_message(
            message,
            actor,
            page=0,
            filter_target_id=None if can_view_all else actor["telegram_id"],
            back_subject_id=actor["telegram_id"],
            can_pay=not can_view_all,
        )

    @router.message(Command("unfine"))
    async def unfine_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        target = await parse_target_only(message, parse_command_args(message.text), "/unfine @player или reply + /unfine")
        removed = await services.remove_paid_fines(actor, target)
        await message.answer(f"Из активных списков убрано оплаченных штрафов: <b>{removed}</b>.")
    @router.message(Command("wanted"))
    async def wanted_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        payload = payload_after_command(message)
        parts = split_pipe_sections(
            payload,
            3,
            "/wanted John Doe | Чёрная куртка, рост 180 | Вооружённое ограбление",
        )
        full_name_text, appearance, reason = parts[:3]
        wanted = await services.issue_wanted(actor, full_name_text, appearance, reason)
        notice = await services.render_dispatch_wanted_notice(wanted, issuer=actor)
        await services.send_topic_notice(message.bot, "wanted", notice)
        await services.notify_government_staff(message.bot, notice)
        await message.answer(f"Розыск #{wanted['id']} добавлен в ориентировки.")

    @router.message(Command("wanteds"))
    async def wanteds_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        await render_wanteds_message(message, actor, 0)

    @router.message(Command("unwanted"))
    async def unwanted_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        if not args:
            raise ServiceError("Пример: /unwanted 4")
        removed = await services.remove_wanted(actor, parse_positive_int(args[0]))
        await message.answer(f"Снято записей из розыска: <b>{removed}</b>.")

    @router.message(Command("setfinechat"))
    async def set_fine_chat_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        if message.chat.type != "supergroup":
            raise ServiceError("Эту команду нужно использовать в супергруппе.")
        await services.set_topic_chat(actor, "fine", message.chat.id, message.message_thread_id)
        await message.answer("Топик для уведомлений о штрафах сохранён.")

    @router.message(Command("setwantedchat"))
    async def set_wanted_chat_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        if message.chat.type != "supergroup":
            raise ServiceError("Эту команду нужно использовать в супергруппе.")
        await services.set_topic_chat(actor, "wanted", message.chat.id, message.message_thread_id)
        await message.answer("Топик для уведомлений о розыске сохранён.")

    @router.message(Command("setvakchat"))
    async def set_vak_chat_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        if message.chat.type != "supergroup":
            raise ServiceError("Эту команду нужно использовать в супергруппе.")
        await services.set_topic_chat(actor, "vak", message.chat.id, message.message_thread_id)
        await message.answer("Топик для торговой площадки и вакансий сохранён.")

    @router.message(Command("allowmega"))
    async def allow_mega_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        target = await parse_target_only(message, parse_command_args(message.text), "/allowmega @player или reply + /allowmega")
        await services.grant_special_access(actor, target, "mega")
        await message.answer(f"{user_link(target)} получил доступ к регистрации мега-корпорации.")

    @router.message(Command("allowconglomerate"))
    async def allow_conglomerate_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        target = await parse_target_only(
            message,
            parse_command_args(message.text),
            "/allowconglomerate @player или reply + /allowconglomerate",
        )
        await services.grant_special_access(actor, target, "conglomerate")
        await message.answer(f"{user_link(target)} получил доступ к регистрации глобального конгломерата.")

    @router.message(Command("market"))
    async def market_handler(message: Message) -> None:
        await actor_from_message(message)
        page_obj = await services.list_market_sales(0)
        await message.answer(render_market_text(page_obj))

    @router.message(Command("sell"))
    async def sell_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        item_name, quantity_raw, price_raw, description = split_pipe_sections(
            payload_after_command(message),
            4,
            "/sell Аптечка | 3 | 500 | Новые, без вскрытия",
        )[:4]
        post = await services.create_sale_post(
            actor,
            item_name,
            parse_positive_int(quantity_raw),
            parse_positive_int(price_raw),
            description,
        )
        notice = join_lines(
            [
                "<b>Montana Market Dispatch</b>",
                f"Продавец: {user_link(actor)}",
                f"Товар: <b>{post['item_name']}</b>",
                f"Количество: <b>{post['quantity']}</b>",
                f"Цена за 1 шт.: <b>{format_money(int(post['price_usd']), 'usd')}</b>",
                f"Описание: {post['body']}",
                f"Номер лота: <b>#{post['id']}</b>",
                "#Продажа",
            ]
        )
        await services.send_topic_notice(message.bot, "vak", notice)
        await message.answer(f"Лот #{post['id']} опубликован на торговой площадке.")

    @router.message(Command("buy"))
    async def buy_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        if len(args) != 2:
            raise ServiceError("Пример: /buy 12 3")
        result = await services.buy_market_sale(actor, parse_positive_int(args[0]), parse_positive_int(args[1]))
        owner = await services.get_user(int(result["owner_id"]))
        if owner is not None:
            await services.maybe_send_private(
                message.bot,
                int(owner["telegram_id"]),
                f"По вашему лоту #{result['id']} куплено {result['bought_quantity']} x {result['item_name']}. "
                f"Зачислено {format_money(int(result['total_price']), 'usd')}.",
            )
        await message.answer(
            f"Покупка выполнена: {result['bought_quantity']} x <b>{result['item_name']}</b> за "
            f"<b>{format_money(int(result['total_price']), 'usd')}</b>."
        )

    @router.message(Command("hire"))
    async def hire_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        post = await services.create_classified_post(actor, "hire", payload_after_command(message))
        notice = join_lines(
            [
                "<b>Montana Jobs</b>",
                f"Автор: {user_link(actor)}",
                post["body"],
                "#ИщюСотрудника",
            ]
        )
        await services.send_topic_notice(message.bot, "vak", notice)
        await message.answer("Вакансия опубликована.")

    @router.message(Command("work"))
    async def work_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        post = await services.create_classified_post(actor, "work", payload_after_command(message))
        notice = join_lines(
            [
                "<b>Montana Jobs</b>",
                f"Автор: {user_link(actor)}",
                post["body"],
                "#ИщюРаботу",
            ]
        )
        await services.send_topic_notice(message.bot, "vak", notice)
        await message.answer("Резюме опубликовано.")

    @router.message(Command("buisnescreate"))
    @router.message(Command("businesscreate"))
    async def business_create_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        direction, name, description, capital_raw = split_pipe_sections(
            payload_after_command(message),
            4,
            "/buisnescreate Магазин | Montana Parts | Продажа автозапчастей | 200000",
        )[:4]
        panel = await services.register_organization(
            actor,
            "business",
            name,
            direction,
            description,
            parse_positive_int(capital_raw),
        )
        await message.answer(render_organization_panel_text(panel) + f"\n\nДоступные направления: {BUSINESS_DIRECTIONS_TEXT}")

    @router.message(Command("companycreate"))
    async def company_create_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        direction, name, description, capital_raw = split_pipe_sections(
            payload_after_command(message),
            4,
            "/companycreate Логистика | Big Sky Cargo | Грузовые перевозки по штату | 3000000",
        )[:4]
        panel = await services.register_organization(
            actor,
            "company",
            name,
            direction,
            description,
            parse_positive_int(capital_raw),
        )
        await message.answer(render_organization_panel_text(panel))

    @router.message(Command("supercreate"))
    async def super_create_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        org_kind, name, description, direction, capital_raw = split_pipe_sections(
            payload_after_command(message),
            5,
            "/supercreate mega | Nebula Group | Международный холдинг | Технологии | 5000000",
        )[:5]
        normalized_kind = org_kind.strip().lower()
        if normalized_kind in {"mega", "megacorp", "мега"}:
            org_type = "megacorp"
        elif normalized_kind in {"conglomerate", "global", "глобальный", "конгломерат"}:
            org_type = "conglomerate"
        else:
            raise ServiceError("Первым параметром укажите mega или conglomerate.")
        panel = await services.register_organization(
            actor,
            org_type,
            name,
            direction,
            description,
            parse_positive_int(capital_raw),
        )
        await message.answer(render_organization_panel_text(panel))

    @router.message(Command("buisnespanel"))
    async def business_panel_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        panel = await services.organization_panel(actor["telegram_id"], BUSINESS_TYPES)
        if panel is None:
            raise ServiceError("Сначала зарегистрируйте бизнес: /buisnescreate Направление | Название | Описание | Капитал")
        await message.answer(
            render_organization_panel_text(panel)
            + "\n\n"
            + join_lines(
                [
                    "/buisnestaff - список сотрудников",
                    "/buisnesaddstaff [reply/@/id] - отправить приглашение",
                    "/buisneslaries [сумма] - зарплата сотрудников",
                    "/buisnesadd [сумма] - пополнить капитал",
                    "/buisnescreaterole [название] - создать роль",
                    "/buisnesroleset [reply/@/id] [роль] - назначить роль",
                    "/buisnesdel - закрыть бизнес",
                ]
            )
        )

    @router.message(Command("companypanel"))
    async def company_panel_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        panel = await services.organization_panel(actor["telegram_id"], COMPANY_TYPES)
        if panel is None:
            raise ServiceError("Сначала зарегистрируйте компанию: /companycreate Направление | Название | Описание | Капитал")
        await message.answer(
            render_organization_panel_text(panel)
            + "\n\n"
            + join_lines(
                [
                    "/companystaff - список сотрудников",
                    "/companyaddstaff [reply/@/id] - отправить приглашение",
                    "/companylaries [сумма] - зарплата сотрудников",
                    "/companyadd [сумма] - пополнить капитал",
                    "/companycreaterole [название] - создать роль",
                    "/companyroleset [reply/@/id] [роль] - назначить роль",
                    "/companydel - закрыть компанию",
                ]
            )
        )

    @router.message(Command("superpanel"))
    async def super_panel_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        panel = await services.organization_panel(actor["telegram_id"], SUPER_TYPES)
        if panel is None:
            raise ServiceError("Сначала зарегистрируйте супер-организацию: /supercreate mega|conglomerate | Название | Описание | Направление | Капитал")
        await message.answer(
            render_organization_panel_text(panel)
            + "\n\n"
            + join_lines(
                [
                    "/superstaff - список сотрудников",
                    "/superaddstaff [reply/@/id] - отправить приглашение",
                    "/superlaries [сумма] - зарплата сотрудников",
                    "/superadd [сумма] - пополнить капитал",
                    "/supercreaterole [название] - создать роль",
                    "/superroleset [reply/@/id] [роль] - назначить роль",
                    "/superdel - закрыть организацию",
                ]
            )
        )

    @router.message(Command("buisnestaff"))
    async def business_staff_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        panel, staff = await services.list_organization_staff(actor, BUSINESS_TYPES)
        lines = [f"<b>Сотрудники: {panel['name']}</b>", ""]
        for member in staff:
            role_label = "Владелец" if member["member_type"] == "owner" else (member.get("custom_role_name") or "Сотрудник")
            lines.append(f"• {user_link(member)} - {role_label}")
        await message.answer(join_lines(lines))

    @router.message(Command("companystaff"))
    async def company_staff_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        panel, staff = await services.list_organization_staff(actor, COMPANY_TYPES)
        lines = [f"<b>Сотрудники: {panel['name']}</b>", ""]
        for member in staff:
            role_label = "Владелец" if member["member_type"] == "owner" else (member.get("custom_role_name") or "Сотрудник")
            lines.append(f"• {user_link(member)} - {role_label}")
        await message.answer(join_lines(lines))

    @router.message(Command("superstaff"))
    async def super_staff_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        panel, staff = await services.list_organization_staff(actor, SUPER_TYPES)
        lines = [f"<b>Сотрудники: {panel['name']}</b>", ""]
        for member in staff:
            role_label = "Владелец" if member["member_type"] == "owner" else (member.get("custom_role_name") or "Сотрудник")
            lines.append(f"• {user_link(member)} - {role_label}")
        await message.answer(join_lines(lines))

    @router.message(Command("buisnesaddstaff"))
    @router.message(Command("biusnesaddstaff"))
    async def business_add_staff_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        target = await parse_target_only(message, parse_command_args(message.text), "/buisnesaddstaff @player или reply + /buisnesaddstaff")
        invite = await services.invite_organization_staff(actor, target, BUSINESS_TYPES)
        await services.maybe_send_private(
            message.bot,
            target["telegram_id"],
            f"Вам пришло приглашение в организацию <b>{invite['organization_name']}</b>. Откройте /balance и нажмите кнопку приглашений.",
        )
        await message.answer(f"Приглашение отправлено игроку {user_link(target)}.")

    @router.message(Command("companyaddstaff"))
    async def company_add_staff_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        target = await parse_target_only(message, parse_command_args(message.text), "/companyaddstaff @player или reply + /companyaddstaff")
        invite = await services.invite_organization_staff(actor, target, COMPANY_TYPES)
        await services.maybe_send_private(
            message.bot,
            target["telegram_id"],
            f"Вам пришло приглашение в организацию <b>{invite['organization_name']}</b>. Откройте /balance и нажмите кнопку приглашений.",
        )
        await message.answer(f"Приглашение отправлено игроку {user_link(target)}.")

    @router.message(Command("superaddstaff"))
    async def super_add_staff_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        target = await parse_target_only(message, parse_command_args(message.text), "/superaddstaff @player или reply + /superaddstaff")
        invite = await services.invite_organization_staff(actor, target, SUPER_TYPES)
        await services.maybe_send_private(
            message.bot,
            target["telegram_id"],
            f"Вам пришло приглашение в организацию <b>{invite['organization_name']}</b>. Откройте /balance и нажмите кнопку приглашений.",
        )
        await message.answer(f"Приглашение отправлено игроку {user_link(target)}.")

    @router.message(Command("buisneslaries"))
    async def business_salary_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        if not args:
            raise ServiceError("Пример: /buisneslaries 2500")
        panel = await services.set_organization_payroll(actor, BUSINESS_TYPES, parse_positive_int(args[0]))
        await message.answer(f"Зарплата сотрудников бизнеса обновлена: <b>{format_money(int(panel['payroll_usd']), 'usd')}</b>.")

    @router.message(Command("companylaries"))
    async def company_salary_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        if not args:
            raise ServiceError("Пример: /companylaries 2500")
        panel = await services.set_organization_payroll(actor, COMPANY_TYPES, parse_positive_int(args[0]))
        await message.answer(f"Зарплата сотрудников компании обновлена: <b>{format_money(int(panel['payroll_usd']), 'usd')}</b>.")

    @router.message(Command("superlaries"))
    async def super_salary_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        if not args:
            raise ServiceError("Пример: /superlaries 2500")
        panel = await services.set_organization_payroll(actor, SUPER_TYPES, parse_positive_int(args[0]))
        await message.answer(f"Зарплата сотрудников обновлена: <b>{format_money(int(panel['payroll_usd']), 'usd')}</b>.")

    @router.message(Command("buisnesadd"))
    async def business_add_capital_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        if not args:
            raise ServiceError("Пример: /buisnesadd 50000")
        panel = await services.add_organization_capital(actor, BUSINESS_TYPES, parse_positive_int(args[0]))
        await message.answer(f"Капитал бизнеса пополнен. Новый баланс капитала: <b>{format_money(int(panel['capital_usd']), 'usd')}</b>.")

    @router.message(Command("companyadd"))
    async def company_add_capital_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        if not args:
            raise ServiceError("Пример: /companyadd 50000")
        panel = await services.add_organization_capital(actor, COMPANY_TYPES, parse_positive_int(args[0]))
        await message.answer(f"Капитал компании пополнен. Новый баланс капитала: <b>{format_money(int(panel['capital_usd']), 'usd')}</b>.")

    @router.message(Command("superadd"))
    async def super_add_capital_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        if not args:
            raise ServiceError("Пример: /superadd 50000")
        panel = await services.add_organization_capital(actor, SUPER_TYPES, parse_positive_int(args[0]))
        await message.answer(f"Капитал организации пополнен. Новый баланс капитала: <b>{format_money(int(panel['capital_usd']), 'usd')}</b>.")

    @router.message(Command("buisnesdel"))
    async def business_delete_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        result = await services.delete_organization(actor, BUSINESS_TYPES)
        await message.answer(
            f"Бизнес <b>{result['name']}</b> закрыт. Возвращено: <b>{format_money(int(result['refund_usd']), 'usd')}</b>. "
            f"Сгорело: <b>{format_money(int(result['burned_usd']), 'usd')}</b>."
        )

    @router.message(Command("companydel"))
    async def company_delete_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        result = await services.delete_organization(actor, COMPANY_TYPES)
        await message.answer(
            f"Компания <b>{result['name']}</b> закрыта. Возвращено: <b>{format_money(int(result['refund_usd']), 'usd')}</b>. "
            f"Сгорело: <b>{format_money(int(result['burned_usd']), 'usd')}</b>."
        )

    @router.message(Command("superdel"))
    async def super_delete_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        result = await services.delete_organization(actor, SUPER_TYPES)
        await message.answer(
            f"Организация <b>{result['name']}</b> закрыта. Возвращено: <b>{format_money(int(result['refund_usd']), 'usd')}</b>. "
            f"Сгорело: <b>{format_money(int(result['burned_usd']), 'usd')}</b>."
        )

    @router.message(Command("buisnescreaterole"))
    async def business_create_role_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        role = await services.create_organization_role(actor, BUSINESS_TYPES, payload_after_command(message))
        await message.answer(f"Создана роль <b>{role['name']}</b>.")

    @router.message(Command("companycreaterole"))
    async def company_create_role_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        role = await services.create_organization_role(actor, COMPANY_TYPES, payload_after_command(message))
        await message.answer(f"Создана роль <b>{role['name']}</b>.")

    @router.message(Command("supercreaterole"))
    async def super_create_role_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        role = await services.create_organization_role(actor, SUPER_TYPES, payload_after_command(message))
        await message.answer(f"Создана роль <b>{role['name']}</b>.")

    @router.message(Command("buisnesroleset"))
    async def business_role_set_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        target, role_name = await parse_target_and_text(
            message,
            parse_command_args(message.text),
            "/buisnesroleset @player НазваниеРоли или reply + /buisnesroleset НазваниеРоли",
        )
        updated = await services.set_organization_member_role(actor, target, BUSINESS_TYPES, role_name)
        await message.answer(f"{user_link(target)} назначена роль <b>{updated['custom_role_name']}</b>.")

    @router.message(Command("companyroleset"))
    async def company_role_set_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        target, role_name = await parse_target_and_text(
            message,
            parse_command_args(message.text),
            "/companyroleset @player НазваниеРоли или reply + /companyroleset НазваниеРоли",
        )
        updated = await services.set_organization_member_role(actor, target, COMPANY_TYPES, role_name)
        await message.answer(f"{user_link(target)} назначена роль <b>{updated['custom_role_name']}</b>.")

    @router.message(Command("superroleset"))
    async def super_role_set_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        target, role_name = await parse_target_and_text(
            message,
            parse_command_args(message.text),
            "/superroleset @player НазваниеРоли или reply + /superroleset НазваниеРоли",
        )
        updated = await services.set_organization_member_role(actor, target, SUPER_TYPES, role_name)
        await message.answer(f"{user_link(target)} назначена роль <b>{updated['custom_role_name']}</b>.")

    @router.message(Command("invest"))
    async def invest_handler(message: Message) -> None:
        actor = await actor_from_message(message)
        args = parse_command_args(message.text)
        if len(args) < 2:
            raise ServiceError("Пример: /invest Montana Logistics 50000")
        amount = parse_positive_int(args[-1])
        organization_name = " ".join(args[:-1]).strip()
        organization = await services.invest_in_organization(actor, organization_name, amount)
        await message.answer(
            f"Инвестиция отправлена в <b>{organization['name']}</b>. Новый капитал: <b>{format_money(int(organization['capital_usd']), 'usd')}</b>."
        )

    @router.callback_query(
        F.data.startswith("balance:")
        | F.data.startswith("history:")
        | F.data.startswith("fines:")
        | F.data.startswith("wanteds:")
        | F.data.startswith("invites:")
    )
    async def callback_router(callback: CallbackQuery) -> None:
        actor = await actor_from_callback(callback)
        data = callback.data or ""
        owner_id = callback_owner(data)
        if owner_id != actor["telegram_id"]:
            await callback.answer("Эта кнопка принадлежит другому игроку.", show_alert=True)
            return
        payload = data.rsplit(":", maxsplit=1)[0]

        if payload.startswith("balance:refresh:"):
            subject_id = int(payload.split(":")[2])
            subject = await services.get_user(subject_id)
            if subject is None:
                await callback.answer("Профиль не найден.", show_alert=True)
                return
            if subject_id != actor["telegram_id"] and actor["role"] not in {"admin", "owner"}:
                await callback.answer("Этот профиль доступен только владельцу кнопки.", show_alert=True)
                return
            await render_balance(callback.message, actor, subject, edit=True)
            await callback.answer()
            return

        if payload.startswith("balance:inventory:"):
            subject_id = int(payload.split(":")[2])
            subject = await services.get_user(subject_id)
            if subject is None:
                await callback.answer("Профиль не найден.", show_alert=True)
                return
            if subject_id != actor["telegram_id"] and actor["role"] not in {"admin", "owner"}:
                await callback.answer("Этот инвентарь доступен только владельцу кнопки.", show_alert=True)
                return
            await render_inventory(callback.message, actor, subject, edit=True)
            await callback.answer()
            return

        if payload.startswith("history:list:"):
            _, _, subject_raw, page_raw = payload.split(":", maxsplit=3)
            subject = await services.get_user(int(subject_raw))
            if subject is None:
                await callback.answer("Профиль не найден.", show_alert=True)
                return
            await render_history_message(callback.message, actor, subject, int(page_raw), edit=True)
            await callback.answer()
            return

        if payload.startswith("invites:list:"):
            page = int(payload.split(":")[2])
            await render_invites_message(callback.message, actor, page, edit=True)
            await callback.answer()
            return

        if payload.startswith("invites:accept:"):
            invite_id = int(payload.split(":")[2])
            await services.respond_organization_invite(actor, invite_id, True)
            await render_invites_message(callback.message, actor, 0, edit=True)
            await callback.answer("Приглашение принято.")
            return

        if payload.startswith("invites:decline:"):
            invite_id = int(payload.split(":")[2])
            await services.respond_organization_invite(actor, invite_id, False)
            await render_invites_message(callback.message, actor, 0, edit=True)
            await callback.answer("Приглашение отклонено.")
            return

        if payload.startswith("fines:list:"):
            _, _, subject_raw, page_raw = payload.split(":", maxsplit=3)
            subject_id = int(subject_raw)
            await render_fines_message(
                callback.message,
                actor,
                page=int(page_raw),
                filter_target_id=None if subject_id == 0 else subject_id,
                back_subject_id=actor["telegram_id"] if subject_id == 0 else subject_id,
                can_pay=subject_id == actor["telegram_id"],
                edit=True,
            )
            await callback.answer()
            return

        if payload.startswith("fines:pay:"):
            fine_id = int(payload.split(":")[2])
            await services.pay_fine(actor, fine_id)
            await render_fines_message(
                callback.message,
                actor,
                page=0,
                filter_target_id=actor["telegram_id"],
                back_subject_id=actor["telegram_id"],
                can_pay=True,
                edit=True,
            )
            await callback.answer("Штраф оплачен.")
            return

        if payload.startswith("wanteds:list:"):
            page = int(payload.split(":")[2])
            await render_wanteds_message(callback.message, actor, page, edit=True)
            await callback.answer()
            return

        await callback.answer()

    return router


