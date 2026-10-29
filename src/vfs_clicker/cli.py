import argparse
import asyncio
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Page, async_playwright

from vfs_clicker.captcha import ManualActionRequired, ManualCaptchaHandler
from vfs_clicker.config import load_config
from vfs_clicker.handoff import ChromeHandoffSession, find_chrome_executable, profile_path
from vfs_clicker.models import Account, SessionResult, SessionStatus
from vfs_clicker.proxies import BridgedProxyProvider
from vfs_clicker.runner import MultiSessionRunner
from vfs_clicker.scenarios import DemoLoginScenario, Scenario, VfsLoginScenario


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    scenario_group = parser.add_mutually_exclusive_group(required=True)
    scenario_group.add_argument("--demo", action="store_true")
    scenario_group.add_argument("--vfs-login", action="store_true")
    parser.add_argument("--no-proxy", action="store_true")
    parser.add_argument("--chrome-handoff", action="store_true")
    args = parser.parse_args()
    if args.chrome_handoff and not args.vfs_login:
        parser.error("--chrome-handoff requires --vfs-login")
    scenario_name = "vfs-login" if args.vfs_login else "demo"
    if args.chrome_handoff:
        coroutine = _run_chrome_handoff(args.config, no_proxy=args.no_proxy)
    else:
        coroutine = _run(args.config, scenario_name, no_proxy=args.no_proxy)
    raise SystemExit(asyncio.run(coroutine))


async def _run(config_path: Path, scenario_name: str, no_proxy: bool = False) -> int:
    config = load_config(config_path)
    runner = MultiSessionRunner(
        proxy_provider=BridgedProxyProvider(() if no_proxy else config.proxies),
        captcha_handler=ManualCaptchaHandler(allow_interactive=not config.headless),
        max_parallel=config.max_parallel,
        timeout_seconds=config.timeout_seconds,
        headless=config.headless,
    )
    results = await runner.run(config.accounts, _create_scenario(scenario_name, config.target_url))
    for result in results:
        print(f"{result.account_id}: {result.status.value}: {result.detail}")
    return 0 if all(result.status is SessionStatus.SUCCEEDED for result in results) else 1


async def _run_chrome_handoff(config_path: Path, no_proxy: bool = False) -> int:
    config = load_config(config_path)
    if len(config.accounts) != 1:
        raise ValueError("Chrome handoff pilot requires exactly one account")

    account = config.accounts[0]
    provider = BridgedProxyProvider(() if no_proxy else config.proxies)
    session: ChromeHandoffSession | None = None
    proxy = None
    result: SessionResult | None = None
    chrome_started = False
    await provider.start()
    try:
        try:
            proxy = await provider.acquire(account, 0)
            profiles_dir = config_path.resolve().parent / ".vfs-profiles"
            session = ChromeHandoffSession(
                chrome_path=find_chrome_executable(),
                profile_dir=profile_path(profiles_dir, account.id),
                target_url=config.target_url,
                proxy=proxy,
            )
            endpoint = await session.start()
            chrome_started = True
            await asyncio.to_thread(
                input,
                f"{account.id}: complete Cloudflare in ordinary Chrome, wait for the login form, then press Enter: ",
            )
            detail = await _continue_handoff(endpoint, config.target_url, account, config.timeout_seconds)
            result = SessionResult(account.id, SessionStatus.SUCCEEDED, detail)
        except ManualActionRequired as error:
            result = SessionResult(account.id, SessionStatus.MANUAL_ACTION_REQUIRED, str(error))
        except Exception as error:
            result = SessionResult(account.id, SessionStatus.FAILED, f"{type(error).__name__}: {error}")

        print(f"{result.account_id}: {result.status.value}: {result.detail}")
        if chrome_started:
            await asyncio.to_thread(
                input,
                f"{account.id}: inspect the browser result, then press Enter to close Chrome: ",
            )
        return 0 if result.status is SessionStatus.SUCCEEDED else 1
    finally:
        if session is not None:
            await session.close()
        if result is not None:
            await provider.release(account, proxy, result)
        await provider.close()


async def _continue_handoff(
    endpoint: str,
    target_url: str,
    account: Account,
    timeout_seconds: float,
) -> str:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
        try:
            if not browser.contexts:
                raise RuntimeError("Attached Chrome has no browser context")
            page = _find_target_page(browser.contexts[0], target_url)
            timeout_ms = timeout_seconds * 1_000
            page.set_default_timeout(timeout_ms)
            page.set_default_navigation_timeout(timeout_ms)
            scenario = VfsLoginScenario(
                target_url,
                stage_reporter=lambda account_id, stage: print(f"{account_id}: {stage}"),
            )
            return await scenario.run_from_login_page(
                page,
                account,
                ManualCaptchaHandler(allow_interactive=True),
            )
        finally:
            await browser.close()


def _find_target_page(context: BrowserContext, target_url: str) -> Page:
    target_host = urlsplit(target_url).hostname
    for page in reversed(context.pages):
        if urlsplit(page.url).hostname == target_host:
            return page
    if context.pages:
        return context.pages[-1]
    raise RuntimeError("Attached Chrome has no open pages")


def _create_scenario(name: str, target_url: str) -> Scenario:
    if name == "demo":
        return DemoLoginScenario(target_url)
    if name == "vfs-login":
        return VfsLoginScenario(
            target_url,
            stage_reporter=lambda account_id, stage: print(f"{account_id}: {stage}"),
        )
    raise ValueError(f"Unknown scenario: {name}")


if __name__ == "__main__":
    main()

