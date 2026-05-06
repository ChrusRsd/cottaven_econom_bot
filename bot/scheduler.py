"""Background scheduler for recurring game mechanics."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from bot.services import EconomyService


logger = logging.getLogger(__name__)


class BackgroundScheduler:
    """Simple in-process scheduler for taxes, salaries, and overdue fines."""

    def __init__(self, services: EconomyService, bot: Bot) -> None:
        self.services = services
        self.bot = bot
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run(), name="montana-scheduler")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # pragma: no cover - defensive log for runtime bot usage
                logger.exception("Scheduled task tick failed.")
            await asyncio.sleep(30)

    async def tick(self) -> None:
        now = self.services.now()

        if await self.services.should_run_business_income(now):
            result = await self.services.pay_business_daily_income()
            await self.services.mark_business_income_run(now)
            logger.info("Business daily income paid: %s", result)

        if await self.services.should_run_weekly_tax(now):
            result = await self.services.collect_weekly_taxes()
            await self.services.mark_weekly_tax_run(now)
            logger.info("Weekly taxes collected: %s", result)

        if await self.services.should_run_company_income(now):
            result = await self.services.pay_company_weekly_income()
            await self.services.mark_company_income_run(now)
            logger.info("Company weekly income paid: %s", result)

        if await self.services.should_run_super_income(now):
            result = await self.services.pay_super_weekly_income()
            await self.services.mark_super_income_run(now)
            logger.info("Super organization weekly income paid: %s", result)

        for slot_index, _ in enumerate(self.services.settings.salary_hours):
            if await self.services.should_run_salary_slot(slot_index, now):
                result = await self.services.pay_government_salaries()
                org_result = await self.services.pay_organization_salaries()
                await self.services.mark_salary_slot_run(slot_index, now)
                logger.info("Government salaries paid: %s", result)
                logger.info("Organization salaries paid: %s", org_result)

        if await self.services.should_run_fine_scan(now):
            wanteds = await self.services.expire_fines_to_wanted()
            await self.services.mark_fine_scan_run(now)
            for wanted in wanteds:
                notice = await self.services.render_dispatch_wanted_notice(wanted, issuer_name=None)
                await self.services.send_topic_notice(self.bot, "wanted", notice)
                await self.services.notify_government_staff(self.bot, notice)
            if wanteds:
                logger.info("Overdue fines converted to wanted notices: %s", len(wanteds))
