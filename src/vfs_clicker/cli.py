import argparse
import asyncio
from pathlib import Path

from vfs_clicker.captcha import ManualCaptchaHandler
from vfs_clicker.config import load_config
from vfs_clicker.models import SessionStatus
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
    args = parser.parse_args()
    scenario_name = "vfs-login" if args.vfs_login else "demo"
    raise SystemExit(asyncio.run(_run(args.config, scenario_name, no_proxy=args.no_proxy)))


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

