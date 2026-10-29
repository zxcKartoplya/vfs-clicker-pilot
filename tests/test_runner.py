import asyncio
from pathlib import Path

import pytest
from playwright.async_api import Page

from vfs_clicker.captcha import CaptchaHandler, ManualCaptchaHandler
from vfs_clicker.models import Account, SessionStatus
from vfs_clicker.proxies import StaticProxyProvider
from vfs_clicker.runner import MultiSessionRunner
from vfs_clicker.scenarios import DemoLoginScenario


class PartiallyFailingScenario:
    async def run(self, page: Page, account: Account, captcha_handler: CaptchaHandler) -> str:
        if account.id == "account-1":
            raise RuntimeError("expected failure")
        return "completed"


@pytest.mark.asyncio
async def test_ten_isolated_sessions_complete_demo_flow() -> None:
    demo_path = Path(__file__).parents[1] / "examples" / "demo.html"
    accounts = tuple(
        Account(id=f"account-{index}", email=f"user{index}@example.test", password="secret")
        for index in range(10)
    )
    runner = MultiSessionRunner(
        proxy_provider=StaticProxyProvider(()),
        captcha_handler=ManualCaptchaHandler(allow_interactive=False),
        max_parallel=4,
        timeout_seconds=20,
        headless=True,
    )

    results = await runner.run(accounts, DemoLoginScenario(str(demo_path)))

    assert len(results) == 10
    assert all(result.status is SessionStatus.SUCCEEDED for result in results)


@pytest.mark.asyncio
async def test_parallel_limit_is_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        MultiSessionRunner(
            proxy_provider=StaticProxyProvider(()),
            captcha_handler=ManualCaptchaHandler(allow_interactive=False),
            max_parallel=0,
            timeout_seconds=20,
            headless=True,
        )

    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_one_session_failure_does_not_stop_other_sessions() -> None:
    accounts = tuple(
        Account(id=f"account-{index}", email=f"user{index}@example.test", password="secret")
        for index in range(3)
    )
    runner = MultiSessionRunner(
        proxy_provider=StaticProxyProvider(()),
        captcha_handler=ManualCaptchaHandler(allow_interactive=False),
        max_parallel=3,
        timeout_seconds=20,
        headless=True,
    )

    results = await runner.run(accounts, PartiallyFailingScenario())

    assert [result.status for result in results] == [
        SessionStatus.SUCCEEDED,
        SessionStatus.FAILED,
        SessionStatus.SUCCEEDED,
    ]
