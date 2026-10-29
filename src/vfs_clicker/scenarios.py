import re
from pathlib import Path
from typing import Protocol

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
    def __init__(self, target: str) -> None:
        self._target = _as_url(target)

    async def run(self, page: Page, account: Account, captcha_handler: CaptchaHandler) -> str:
        response = await self._navigate(page, account, captcha_handler)
        if (response is not None and response.status == 403) or await self._has_cloudflare_challenge(page):
            await captcha_handler.handle(page, account, "Cloudflare verification")

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
        await email.fill(account.email)
        await password.fill(account.password)
        await submit.click()
        return "login form submitted"

    async def _navigate(
        self,
        page: Page,
        account: Account,
        captcha_handler: CaptchaHandler,
    ) -> Response | None:
        try:
            return await page.goto(self._target, wait_until="domcontentloaded")
        except PlaywrightError as error:
            if "ERR_SOCKET_NOT_CONNECTED" not in str(error):
                raise
            await captcha_handler.handle(page, account, "VFS connection or security verification")
            return await page.goto(self._target, wait_until="domcontentloaded")

    async def _has_cloudflare_challenge(self, page: Page) -> bool:
        title = (await page.title()).lower()
        if "just a moment" in title or "security verification" in title:
            return True
        return await page.locator("iframe[src*='challenges.cloudflare.com']").count() > 0


def _as_url(value: str) -> str:
    if "://" in value:
        return value
    return Path(value).resolve().as_uri()

