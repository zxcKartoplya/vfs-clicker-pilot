from pathlib import Path
from typing import Any, cast

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, async_playwright

from vfs_clicker.captcha import ManualActionRequired
from vfs_clicker.models import Account
from vfs_clicker.scenarios import VfsLoginScenario


class UnexpectedCaptchaHandler:
    async def handle(self, page: Page, account: Account, challenge: str) -> None:
        raise AssertionError(f"Unexpected challenge: {challenge}")


class ResolvingCaptchaHandler:
    def __init__(self) -> None:
        self.challenges: list[str] = []

    async def handle(self, page: Page, account: Account, challenge: str) -> None:
        self.challenges.append(challenge)
        await page.get_by_test_id("challenge").evaluate("element => element.remove()")
        await page.locator("#login-form").evaluate("element => element.hidden = false")
        await page.evaluate("document.title = 'VFS login demo'")


class ResolvingPostSubmitCaptchaHandler:
    def __init__(self) -> None:
        self.challenges: list[str] = []

    async def handle(self, page: Page, account: Account, challenge: str) -> None:
        self.challenges.append(challenge)
        await page.evaluate("document.title = 'Verification completed'")


class AcknowledgingCaptchaHandler:
    async def handle(self, page: Page, account: Account, challenge: str) -> None:
        return None


class SocketRetryPage:
    def __init__(self) -> None:
        self.attempts = 0

    async def goto(self, target: str, wait_until: str) -> None:
        self.attempts += 1
        if self.attempts == 1:
            raise PlaywrightError("net::ERR_SOCKET_NOT_CONNECTED")

    async def title(self) -> str:
        return "VFS login"

    def locator(self, selector: str) -> Any:
        return EmptyLocator()


class EmptyLocator:
    async def count(self) -> int:
        return 0


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
async def test_vfs_login_scenario_continues_from_attached_login_page() -> None:
    page_path = Path(__file__).parents[1] / "examples" / "vfs_login_demo.html"
    account = Account(id="account-1", email="user@example.test", password="secret")
    stages: list[tuple[str, str]] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page()
        await page.goto(page_path.resolve().as_uri())
        result = await VfsLoginScenario(
            str(page_path),
            stage_reporter=lambda *args: stages.append(args),
        ).run_from_login_page(page, account, UnexpectedCaptchaHandler())

        assert result == "login form submitted"
        assert stages == [
            ("account-1", "attached to existing Chrome"),
            ("account-1", "login form ready"),
            ("account-1", "login form submitted"),
        ]
        await browser.close()


@pytest.mark.asyncio
async def test_vfs_login_scenario_rejects_handoff_before_cloudflare_is_complete() -> None:
    page_path = Path(__file__).parents[1] / "examples" / "vfs_challenge_demo.html"
    account = Account(id="account-1", email="user@example.test", password="secret")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page()
        await page.goto(page_path.resolve().as_uri())

        with pytest.raises(ManualActionRequired, match="before handing Chrome"):
            await VfsLoginScenario(str(page_path)).run_from_login_page(
                page,
                account,
                UnexpectedCaptchaHandler(),
            )

        await browser.close()


@pytest.mark.asyncio
async def test_vfs_login_scenario_pauses_for_cloudflare_challenge() -> None:
    page_path = Path(__file__).parents[1] / "examples" / "vfs_challenge_demo.html"
    account = Account(id="account-1", email="user@example.test", password="secret")
    captcha_handler = ResolvingCaptchaHandler()
    stages: list[tuple[str, str]] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page()
        result = await VfsLoginScenario(
            str(page_path),
            stage_reporter=lambda *args: stages.append(args),
        ).run(page, account, captcha_handler)

        assert captcha_handler.challenges == ["Cloudflare verification"]
        assert result == "login form submitted"
        await browser.close()

    assert stages == [
        ("account-1", "opening VFS login page"),
        ("account-1", "Cloudflare verification detected"),
        ("account-1", "waiting for Cloudflare clearance"),
        ("account-1", "Cloudflare verification completed"),
        ("account-1", "login form ready"),
        ("account-1", "login form submitted"),
    ]


@pytest.mark.asyncio
async def test_vfs_login_scenario_reports_unresolved_cloudflare_challenge() -> None:
    page_path = Path(__file__).parents[1] / "examples" / "vfs_challenge_demo.html"
    account = Account(id="account-1", email="user@example.test", password="secret")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page()
        page.set_default_timeout(50)

        with pytest.raises(ManualActionRequired, match="another proxy or --no-proxy"):
            await VfsLoginScenario(str(page_path)).run(
                page,
                account,
                AcknowledgingCaptchaHandler(),
            )

        await browser.close()


@pytest.mark.asyncio
async def test_vfs_login_scenario_reports_stages_without_credentials() -> None:
    page_path = Path(__file__).parents[1] / "examples" / "vfs_login_demo.html"
    account = Account(id="account-1", email="user@example.test", password="secret")
    stages: list[tuple[str, str]] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page()
        await VfsLoginScenario(str(page_path), stage_reporter=lambda *args: stages.append(args)).run(
            page,
            account,
            UnexpectedCaptchaHandler(),
        )
        await browser.close()

    assert stages == [
        ("account-1", "opening VFS login page"),
        ("account-1", "login form ready"),
        ("account-1", "login form submitted"),
    ]
    assert all(account.email not in stage and account.password not in stage for _, stage in stages)


@pytest.mark.asyncio
async def test_vfs_login_scenario_retries_socket_error_without_captcha_prompt() -> None:
    account = Account(id="account-1", email="user@example.test", password="secret")
    stages: list[tuple[str, str]] = []
    page = SocketRetryPage()
    scenario = VfsLoginScenario(
        "https://example.test",
        stage_reporter=lambda *args: stages.append(args),
    )

    response = await scenario._navigate(cast(Page, page), account)

    assert response is None
    assert page.attempts == 2
    assert stages == [("account-1", "retrying connection after browser socket error")]


@pytest.mark.asyncio
async def test_vfs_login_scenario_handles_additional_verification_after_submit(
    tmp_path: Path,
) -> None:
    page_path = tmp_path / "post-submit-challenge.html"
    page_path.write_text(
        """<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>VFS login demo</title></head>
  <body>
    <form id="login-form">
      <input type="email" autocomplete="username" required>
      <input type="password" autocomplete="current-password" required>
      <button type="submit">Sign in</button>
    </form>
    <script>
      document.querySelector("#login-form").addEventListener("submit", (event) => {
        event.preventDefault();
        document.title = "Security verification";
      });
    </script>
  </body>
</html>
""",
        encoding="utf-8",
    )
    account = Account(id="account-1", email="user@example.test", password="secret")
    captcha_handler = ResolvingPostSubmitCaptchaHandler()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page()
        result = await VfsLoginScenario(str(page_path)).run(page, account, captcha_handler)
        await browser.close()

    assert result == "login form submitted"
    assert captcha_handler.challenges == ["VFS login verification"]
