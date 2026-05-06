"""Entrypoint for the Montana economy Telegram bot."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from bot.config import load_settings
from bot.database import Database
from bot.handlers import build_router
from bot.scheduler import BackgroundScheduler
from bot.services import EconomyService


try:  # aiogram >= 3.7
    from aiogram.client.default import DefaultBotProperties
except ImportError:  # pragma: no cover
    DefaultBotProperties = None


async def set_bot_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="help", description="Команды жителя штата"),
        BotCommand(command="balance", description="Личный кабинет"),
        BotCommand(command="inventory", description="Ваш инвентарь"),
        BotCommand(command="id", description="ID игрока"),
        BotCommand(command="stikid", description="ID стикера"),
        BotCommand(command="pay", description="Перевести деньги"),
        BotCommand(command="check", description="Создать чек"),
        BotCommand(command="accept", description="Получить чек"),
        BotCommand(command="top", description="Топ по USD"),
        BotCommand(command="stats", description="Статистика богатейших"),
        BotCommand(command="treasuryusa", description="Казна штата"),
        BotCommand(command="wanteds", description="Список розыска"),
        BotCommand(command="market", description="Торговая площадка"),
        BotCommand(command="sell", description="Выставить предмет"),
        BotCommand(command="buy", description="Купить предмет"),
        BotCommand(command="hire", description="Ищу сотрудника"),
        BotCommand(command="work", description="Ищу работу"),
        BotCommand(command="invest", description="Вложить в организацию"),
        BotCommand(command="buisnescreate", description="Создать бизнес"),
        BotCommand(command="companycreate", description="Создать компанию"),
        BotCommand(command="supercreate", description="Создать супер-организацию"),
        BotCommand(command="buisnespanel", description="Панель бизнеса"),
        BotCommand(command="buisnestaff", description="Сотрудники бизнеса"),
        BotCommand(command="buisnesaddstaff", description="Пригласить в бизнес"),
        BotCommand(command="buisneslaries", description="Зарплата бизнеса"),
        BotCommand(command="buisnesadd", description="Пополнить бизнес"),
        BotCommand(command="buisnesdel", description="Удалить бизнес"),
        BotCommand(command="buisnescreaterole", description="Роль в бизнесе"),
        BotCommand(command="buisnesroleset", description="Назначить роль в бизнесе"),
        BotCommand(command="companypanel", description="Панель компании"),
        BotCommand(command="companystaff", description="Сотрудники компании"),
        BotCommand(command="companyaddstaff", description="Пригласить в компанию"),
        BotCommand(command="companylaries", description="Зарплата компании"),
        BotCommand(command="companyadd", description="Пополнить компанию"),
        BotCommand(command="companydel", description="Удалить компанию"),
        BotCommand(command="companycreaterole", description="Роль в компании"),
        BotCommand(command="companyroleset", description="Назначить роль в компании"),
        BotCommand(command="superpanel", description="Панель супер-организации"),
        BotCommand(command="superstaff", description="Сотрудники супер-организации"),
        BotCommand(command="superaddstaff", description="Пригласить в супер-организацию"),
        BotCommand(command="superlaries", description="Зарплата супер-организации"),
        BotCommand(command="superadd", description="Пополнить супер-организацию"),
        BotCommand(command="superdel", description="Удалить супер-организацию"),
        BotCommand(command="supercreaterole", description="Роль в супер-организации"),
        BotCommand(command="superroleset", description="Назначить роль в супер-организации"),
    ]
    await bot.set_my_commands(commands)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    settings = load_settings()
    database = Database(settings)
    await database.connect()
    services = EconomyService(settings, database)

    if DefaultBotProperties is not None:
        bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    else:
        bot = Bot(token=settings.bot_token, parse_mode=ParseMode.HTML)

    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(services))

    scheduler = BackgroundScheduler(services, bot)
    scheduler.start()

    await set_bot_commands(bot)

    try:
        await dispatcher.start_polling(bot)
    finally:
        await scheduler.stop()
        await bot.session.close()
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
