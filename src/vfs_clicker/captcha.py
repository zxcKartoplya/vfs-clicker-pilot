import asyncio
from typing import Protocol

from playwright.async_api import Page

from vfs_clicker.models import Account

__all__ = ["CaptchaHandler", "ManualActionRequired", "ManualCaptchaHandler"]


class ManualActionRequired(RuntimeError):
    pass


class CaptchaHandler(Protocol):
    async def handle(self, page: Page, account: Account, challenge: str) -> None: ...


class ManualCaptchaHandler:
    def __init__(self, allow_interactive: bool) -> None:
        self._allow_interactive = allow_interactive
        self._lock = asyncio.Lock()

    async def handle(self, page: Page, account: Account, challenge: str) -> None:
        if not self._allow_interactive:
            raise ManualActionRequired(f"{account.id}: {challenge}")
        async with self._lock:
            await page.bring_to_front()
            await asyncio.to_thread(input, f"{account.id}: complete {challenge} and press Enter: ")

