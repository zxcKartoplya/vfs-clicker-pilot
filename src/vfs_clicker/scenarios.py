import re
from pathlib import Path
from typing import Callable, Protocol

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page, Response, TimeoutError as PlaywrightTimeoutError, expect

from vfs_clicker.captcha import CaptchaHandler, ManualActionRequired
from vfs_clicker.models import Account

__all__ = ["DemoLoginScenario", "Scenario", "VfsBookingScenario", "VfsLoginScenario"]

_EMAIL_SELECTOR = ", ".join(
    f"{selector}:visible"
    for selector in (
        "input[type='email']",
        "input[name*='email' i]",
        "input[id*='email' i]",
        "input[formcontrolname*='email' i]",
        "input[placeholder*='email' i]",
        "input[autocomplete='username']",
    )
)
_PASSWORD_SELECTOR = ", ".join(
    f"{selector}:visible"
    for selector in (
        "input[type='password']",
        "input[name*='password' i]",
        "input[id*='password' i]",
        "input[formcontrolname*='password' i]",
        "input[autocomplete='current-password']",
    )
)


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
        email = self.email_locator(page)
        if (response is not None and response.status == 403) or await self._has_cloudflare_challenge(page):
            self._report(account, "Cloudflare verification detected")
            await captcha_handler.handle(page, account, "Cloudflare verification")
            self._report(account, "waiting for Cloudflare clearance")
            await self._wait_for_cloudflare_clearance(page, email)
            self._report(account, "Cloudflare verification completed")

        return await self._submit_login_form(page, account, captcha_handler, email)

    async def run_from_login_page(
        self,
        page: Page,
        account: Account,
        captcha_handler: CaptchaHandler,
    ) -> str:
        self._report(account, "attached to existing Chrome")
        email = self.email_locator(page)
        if not await email.is_visible():
            if await self._has_cloudflare_challenge(page):
                raise ManualActionRequired("Complete Cloudflare before handing Chrome to the clicker")
            raise RuntimeError("VFS login form is not visible in the attached Chrome window")
        return await self._submit_login_form(page, account, captcha_handler, email)

    async def _submit_login_form(
        self,
        page: Page,
        account: Account,
        captcha_handler: CaptchaHandler,
        email: Locator,
    ) -> str:
        await self._dismiss_cookie_banner(page, account)
        password = page.locator(_PASSWORD_SELECTOR).first
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
        self._report(account, "login credentials filled")
        if not await submit.is_enabled():
            self._report(account, "VFS login CAPTCHA required")
            await captcha_handler.handle(page, account, "VFS login CAPTCHA")
        try:
            await submit.click()
        except PlaywrightTimeoutError as error:
            if not await submit.is_enabled():
                raise ManualActionRequired("VFS login CAPTCHA was not completed") from error
            raise
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
        if await self.has_visible_login_form(page):
            return False
        return await page.locator("iframe[src*='challenges.cloudflare.com']").count() > 0

    async def _dismiss_cookie_banner(self, page: Page, account: Account) -> None:
        reject = page.get_by_role(
            "button",
            name=re.compile(r"reject all|decline all|отклонить все", re.IGNORECASE),
        ).first
        if await reject.is_visible():
            await reject.click()
            self._report(account, "cookie banner dismissed")

    async def _wait_for_cloudflare_clearance(self, page: Page, email: Locator) -> None:
        try:
            await email.wait_for(state="visible")
        except PlaywrightTimeoutError as error:
            if await self._has_cloudflare_challenge(page):
                raise ManualActionRequired(
                    "Cloudflare clearance was not received; retry with another proxy or --no-proxy"
                ) from error
            raise

    def _report(self, account: Account, stage: str) -> None:
        if self._stage_reporter is not None:
            self._stage_reporter(account.id, stage)

    @staticmethod
    def email_locator(page: Page) -> Locator:
        return page.locator(_EMAIL_SELECTOR).first

    @classmethod
    async def has_visible_login_form(cls, page: Page) -> bool:
        try:
            return await cls.email_locator(page).is_visible()
        except PlaywrightError:
            return False


class VfsBookingScenario:
    def __init__(
        self,
        stage_reporter: Callable[[str, str], None] | None = None,
    ) -> None:
        self._stage_reporter = stage_reporter

    async def fill_from_current_page(self, page: Page, account: Account) -> str:
        booking_form = page.get_by_role(
            "heading",
            name=re.compile(r"^appointment details$", re.IGNORECASE),
        ).first
        if not await booking_form.is_visible():
            start_booking = page.locator("button:visible, a:visible").filter(
                has_text=re.compile(r"^\s*start new booking\s*$", re.IGNORECASE),
            ).first
            try:
                await start_booking.wait_for(state="visible")
            except PlaywrightTimeoutError as error:
                raise RuntimeError(
                    "VFS authorization was not confirmed: Start New Booking is unavailable"
                ) from error
            self._report(account, "authorization confirmed")
            self._report(account, "opening booking form")
            await start_booking.click()
            await booking_form.wait_for(state="visible")
        else:
            self._report(account, "authorization confirmed")

        self._report(account, "booking form ready")
        comboboxes = page.locator("select:visible, [role='combobox']:visible")
        await comboboxes.nth(2).wait_for(state="visible")
        stages = (
            ("application centre", "application centre selected"),
            ("appointment category", "appointment category selected"),
            ("sub-category", "sub-category selected"),
        )
        for index, (field_name, stage) in enumerate(stages):
            await self._choose_first_option(page, comboboxes.nth(index), field_name)
            self._report(account, stage)

        self._report(account, "booking form filled, not submitted")
        return "booking form filled, not submitted"

    async def is_ready(self, page: Page) -> bool:
        start_booking = page.locator("button:visible, a:visible").filter(
            has_text=re.compile(r"^\s*start new booking\s*$", re.IGNORECASE),
        ).first
        booking_form = page.get_by_role(
            "heading",
            name=re.compile(r"^appointment details$", re.IGNORECASE),
        ).first
        return await start_booking.is_visible() or await booking_form.is_visible()

    async def _choose_first_option(
        self,
        page: Page,
        combobox: Locator,
        field_name: str,
    ) -> None:
        await expect(combobox).to_be_enabled()
        tag_name = await combobox.evaluate("element => element.tagName")
        if tag_name == "SELECT":
            options = combobox.locator("option:not([disabled])")
            for index in range(await options.count()):
                option = options.nth(index)
                text = (await option.inner_text()).strip()
                if text and not re.match(r"^(choose|select)\b", text, re.IGNORECASE):
                    await combobox.select_option(label=text)
                    return
            raise RuntimeError(f"Booking field '{field_name}' has no selectable options")

        await combobox.click()
        options = page.locator(
            "[role='option']:visible:not([aria-disabled='true']):not([disabled])"
        )
        await options.first.wait_for(state="visible")
        for index in range(await options.count()):
            option = options.nth(index)
            text = (await option.inner_text()).strip()
            if text and not re.match(r"^(choose|select)\b", text, re.IGNORECASE):
                await option.click()
                return
        raise RuntimeError(f"Booking field '{field_name}' has no selectable options")

    def _report(self, account: Account, stage: str) -> None:
        if self._stage_reporter is not None:
            self._stage_reporter(account.id, stage)


def _as_url(value: str) -> str:
    if "://" in value:
        return value
    return Path(value).resolve().as_uri()

