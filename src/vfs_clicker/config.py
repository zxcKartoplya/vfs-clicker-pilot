import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vfs_clicker.models import Account, ProxySettings

__all__ = ["AppConfig", "load_config"]


@dataclass(frozen=True, slots=True)
class AppConfig:
    target_url: str
    accounts: tuple[Account, ...]
    proxies: tuple[ProxySettings, ...]
    headless: bool
    max_parallel: int
    timeout_seconds: float


def load_config(path: Path) -> AppConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Config root must be an object")

    accounts = tuple(_parse_account(item) for item in _require_list(raw, "accounts"))
    if not accounts:
        raise ValueError("At least one account is required")
    if len(accounts) > 10:
        raise ValueError("Pilot supports at most 10 accounts")

    proxies = tuple(ProxySettings.from_url(value) for value in _require_list(raw, "proxies"))
    max_parallel = int(raw.get("max_parallel", len(accounts)))
    if max_parallel < 1 or max_parallel > 10:
        raise ValueError("max_parallel must be between 1 and 10")

    timeout_seconds = float(raw.get("timeout_seconds", 30))
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    return AppConfig(
        target_url=_require_string(raw, "target_url"),
        accounts=accounts,
        proxies=proxies,
        headless=_optional_bool(raw, "headless", True),
        max_parallel=max_parallel,
        timeout_seconds=timeout_seconds,
    )


def _parse_account(value: Any) -> Account:
    if not isinstance(value, dict):
        raise ValueError("Each account must be an object")
    return Account(
        id=_require_string(value, "id"),
        email=_require_string(value, "email"),
        password=_require_string(value, "password"),
    )


def _require_list(value: dict[str, Any], key: str) -> list[Any]:
    item = value.get(key, [])
    if not isinstance(item, list):
        raise ValueError(f"{key} must be an array")
    return item


def _require_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return item


def _optional_bool(value: dict[str, Any], key: str, default: bool) -> bool:
    item = value.get(key, default)
    if not isinstance(item, bool):
        raise ValueError(f"{key} must be a boolean")
    return item

