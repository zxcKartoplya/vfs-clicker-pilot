import asyncio

from playwright.async_api import Browser, BrowserContext, async_playwright

from vfs_clicker.captcha import CaptchaHandler, ManualActionRequired
from vfs_clicker.models import Account, SessionResult, SessionStatus
from vfs_clicker.proxies import ProxyProvider
from vfs_clicker.scenarios import Scenario

__all__ = ["MultiSessionRunner"]


class MultiSessionRunner:
    def __init__(
        self,
        proxy_provider: ProxyProvider,
        captcha_handler: CaptchaHandler,
        max_parallel: int,
        timeout_seconds: float,
        headless: bool,
    ) -> None:
        if max_parallel < 1:
            raise ValueError("max_parallel must be positive")
        self._proxy_provider = proxy_provider
        self._captcha_handler = captcha_handler
        self._max_parallel = max_parallel
        self._timeout_seconds = timeout_seconds
        self._headless = headless

    async def run(self, accounts: tuple[Account, ...], scenario: Scenario) -> tuple[SessionResult, ...]:
        semaphore = asyncio.Semaphore(self._max_parallel)
        await self._proxy_provider.start()
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(channel="chrome", headless=self._headless)
                try:
                    tasks = [
                        asyncio.create_task(self._run_one(browser, semaphore, account, index, scenario))
                        for index, account in enumerate(accounts)
                    ]
                    return tuple(await asyncio.gather(*tasks))
                finally:
                    await browser.close()
        finally:
            await self._proxy_provider.close()

    async def _run_one(
        self,
        browser: Browser,
        semaphore: asyncio.Semaphore,
        account: Account,
        index: int,
        scenario: Scenario,
    ) -> SessionResult:
        async with semaphore:
            proxy = None
            context: BrowserContext | None = None
            try:
                proxy = await self._proxy_provider.acquire(account, index)
                options = {"proxy": proxy.as_playwright_options()} if proxy else {}
                context = await browser.new_context(**options)
                page = await context.new_page()
                self._configure_page(page)
                detail = await asyncio.wait_for(
                    scenario.run(page, account, self._captcha_handler),
                    timeout=self._timeout_seconds,
                )
                result = SessionResult(account.id, SessionStatus.SUCCEEDED, detail)
            except ManualActionRequired as error:
                result = SessionResult(account.id, SessionStatus.MANUAL_ACTION_REQUIRED, str(error))
            except Exception as error:
                result = SessionResult(account.id, SessionStatus.FAILED, f"{type(error).__name__}: {error}")
            finally:
                if context is not None:
                    await context.close()
            await self._proxy_provider.release(account, proxy, result)
            return result

    def _configure_page(self, page: Page) -> None:
        timeout_ms = self._timeout_seconds * 1_000
        page.set_default_timeout(timeout_ms)
        page.set_default_navigation_timeout(timeout_ms)

