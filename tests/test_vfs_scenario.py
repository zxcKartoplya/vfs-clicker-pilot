from pathlib import Path

import pytest
from playwright.async_api import Page, async_playwright

from vfs_clicker.models import Account
from vfs_clicker.scenarios import VfsLoginScenario


class UnexpectedCaptchaHandler:
    async def handle(self, page: Page, account: Account, challenge: str) -> None:
        raise AssertionError(f"Unexpected challenge: {challenge}")


class ResolvingCaptchaHandler:
    def __init__(self) -> None:
        self.called = False

    async def handle(self, page: Page, account: Account, challenge: str) -> None:
        self.called = True
        await page.get_by_test_id("challenge").evaluate("element => element.remove()")
        await page.locator("#login-form").evaluate("element => element.hidden = false")


@pytest.mark.asyncio
async def test_vfs_login_scenario_submits_semantic_login_form() -> None:
    page_path = Path(__file__).parents[1] / "examples" / "vfs_login_demo.html"
    account = Account(id="account-1", email="user@example.test", password="secret")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page()
        result = await VfsLoginScenario(str(page_path)).run(page, account, UnexpectedCaptchaHandler())

        assert result == "login form submitted"
        await page.get_by_test_id("result").wait_for(state="visible")
        await browser.close()


@pytest.mark.asyncio
async def test_vfs_login_scenario_pauses_for_cloudflare_challenge() -> None:
    page_path = Path(__file__).parents[1] / "examples" / "vfs_challenge_demo.html"
    account = Account(id="account-1", email="user@example.test", password="secret")
    captcha_handler = ResolvingCaptchaHandler()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page()
        result = await VfsLoginScenario(str(page_path)).run(page, account, captcha_handler)

        assert captcha_handler.called
        assert result == "login form submitted"
        await browser.close()
