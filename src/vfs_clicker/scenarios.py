import re
from pathlib import Path
from typing import Callable, Protocol

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Response, expect

from vfs_clicker.captcha import CaptchaHandler
from vfs_clicker.models import Account

__all__ = ["DemoLoginScenario", "Scenario", "VfsLoginScenario"]


class Scenario(Protocol):
    async def run(self, page: Page, account: Account, captcha_handler: CaptchaHandler) -> str: ...


class DemoLoginScenario:
    def __init__(self, target: str) -> None:
        self._target = _as_url(target)

    async def run(self, page: Page, account: Account, captcha_handler: CaptchaHandler) -> str:
        await page.goto(self._target, wait_until="domcontentloaded")
        await page.get_by_test_id("email").fill(account.email)
        await page.get_by_test_id("password").fill(account.password)
        await page.get_by_test_id("continue").click()
        result = page.get_by_test_id("result")
        await expect(result).to_have_text("success")
        return "demo flow completed"


class VfsLoginScenario:
    def __init__(
        self,
        target: str,
        stage_reporter: Callable[[str, str], None] | None = None,
    ) -> None:
        self._target = _as_url(target)
        self._stage_reporter = stage_reporter

    async def run(self, page: Page, account: Account, captcha_handler: CaptchaHandler) -> str:
        self._report(account, "opening VFS login page")
        response = await self._navigate(page, account)
        if (response is not None and response.status == 403) or await self._has_cloudflare_challenge(page):
            self._report(account, "Cloudflare verification detected")
            await captcha_handler.handle(page, account, "Cloudflare verification")
            self._report(account, "Cloudflare verification completed")

        email = page.locator(
            "input[type='email'], input[name*='email' i], input[autocomplete='username']"
        ).first
        password = page.locator(
            "input[type='password'], input[name*='password' i], input[autocomplete='current-password']"
        ).first
        submit = page.get_by_role(
            "button",
            name=re.compile(r"sign in|log in|continue|войти|продолжить", re.IGNORECASE),
        ).first

        await email.wait_for(state="visible")
        await password.wait_for(state="visible")
        await submit.wait_for(state="visible")
        self._report(account, "login form ready")
        await email.fill(account.email)
        await password.fill(account.password)
        await submit.click()
        self._report(account, "login form submitted")
        await page.wait_for_timeout(1_000)
        if await self._has_cloudflare_challenge(page):
            self._report(account, "additional verification detected after submit")
            await captcha_handler.handle(page, account, "VFS login verification")
            self._report(account, "additional verification completed")
        return "login form submitted"

    async def _navigate(self, page: Page, account: Account) -> Response | None:
        try:
            return await page.goto(self._target, wait_until="domcontentloaded")
        except PlaywrightError as error:
            if "ERR_SOCKET_NOT_CONNECTED" not in str(error):
                raise
            if await self._has_cloudflare_challenge(page):
                return None
            self._report(account, "retrying connection after browser socket error")
            try:
                return await page.goto(self._target, wait_until="domcontentloaded")
            except PlaywrightError as retry_error:
                if "ERR_SOCKET_NOT_CONNECTED" not in str(retry_error):
                    raise
                raise RuntimeError(
                    "VFS page did not load after one browser socket reconnect attempt"
                ) from retry_error

    async def _has_cloudflare_challenge(self, page: Page) -> bool:
        title = (await page.title()).lower()
        if "just a moment" in title or "security verification" in title:
            return True
        return await page.locator("iframe[src*='challenges.cloudflare.com']").count() > 0

    def _report(self, account: Account, stage: str) -> None:
        if self._stage_reporter is not None:
            self._stage_reporter(account.id, stage)


def _as_url(value: str) -> str:
    if "://" in value:
        return value
    return Path(value).resolve().as_uri()

