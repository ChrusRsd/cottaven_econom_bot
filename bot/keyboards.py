"""Inline keyboards for panels and lists."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def _owned(data: str, owner_id: int) -> str:
    return f"{data}:{owner_id}"


def balance_keyboard(owner_id: int, subject_id: int, has_fines: bool, has_invites: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🟢 Обновить", callback_data=_owned(f"balance:refresh:{subject_id}", owner_id))
    builder.button(text="🔵 Инвентарь", callback_data=_owned(f"balance:inventory:{subject_id}", owner_id))
    builder.button(text="🟣 История", callback_data=_owned(f"history:list:{subject_id}:0", owner_id))
    if has_fines:
        builder.button(text="Штрафы", callback_data=_owned(f"fines:list:{subject_id}:0", owner_id))
    if has_invites:
        builder.button(text="Приглашения", callback_data=_owned("invites:list:0", owner_id))
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def inventory_keyboard(owner_id: int, subject_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="К балансу", callback_data=_owned(f"balance:refresh:{subject_id}", owner_id))
    builder.button(text="🔄 Обновить", callback_data=_owned(f"balance:inventory:{subject_id}", owner_id))
    builder.adjust(2)
    return builder.as_markup()


def history_keyboard(owner_id: int, subject_id: int, page: int, total_pages: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if total_pages > 1:
        if page > 0:
            builder.button(text="Назад", callback_data=_owned(f"history:list:{subject_id}:{page - 1}", owner_id))
        if page < total_pages - 1:
            builder.button(text="Вперёд", callback_data=_owned(f"history:list:{subject_id}:{page + 1}", owner_id))
    builder.button(text="К балансу", callback_data=_owned(f"balance:refresh:{subject_id}", owner_id))
    builder.adjust(2, 1)
    return builder.as_markup()


def fines_keyboard(
    owner_id: int,
    filter_subject_id: int,
    back_subject_id: int,
    page: int,
    total_pages: int,
    payable_fine_ids: list[int],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for fine_id in payable_fine_ids:
        builder.button(
            text=f"Оплатить #{fine_id}",
            callback_data=_owned(f"fines:pay:{fine_id}", owner_id),
        )
    if total_pages > 1:
        if page > 0:
            builder.button(text="Назад", callback_data=_owned(f"fines:list:{filter_subject_id}:{page - 1}", owner_id))
        if page < total_pages - 1:
            builder.button(text="Вперёд", callback_data=_owned(f"fines:list:{filter_subject_id}:{page + 1}", owner_id))
    builder.button(text="К балансу", callback_data=_owned(f"balance:refresh:{back_subject_id}", owner_id))
    builder.adjust(1)
    return builder.as_markup()


def invites_keyboard(owner_id: int, page: int, total_pages: int, invite_ids: list[int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for invite_id in invite_ids:
        builder.button(text=f"✅ Принять #{invite_id}", callback_data=_owned(f"invites:accept:{invite_id}", owner_id))
        builder.button(text=f"❌ Отклонить #{invite_id}", callback_data=_owned(f"invites:decline:{invite_id}", owner_id))
    if total_pages > 1:
        if page > 0:
            builder.button(text="Назад", callback_data=_owned(f"invites:list:{page - 1}", owner_id))
        if page < total_pages - 1:
            builder.button(text="Вперёд", callback_data=_owned(f"invites:list:{page + 1}", owner_id))
    builder.button(text="К балансу", callback_data=_owned(f"balance:refresh:{owner_id}", owner_id))
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def wanteds_keyboard(owner_id: int, page: int, total_pages: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if total_pages > 1:
        if page > 0:
            builder.button(text="Назад", callback_data=_owned(f"wanteds:list:{page - 1}", owner_id))
        if page < total_pages - 1:
            builder.button(text="Вперёд", callback_data=_owned(f"wanteds:list:{page + 1}", owner_id))
    builder.adjust(2)
    return builder.as_markup()


def callback_owner(data: str) -> int:
    return int(data.rsplit(":", maxsplit=1)[1])
