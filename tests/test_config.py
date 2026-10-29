import json
from pathlib import Path

import pytest

from vfs_clicker.config import load_config
from vfs_clicker.models import Account, ProxySettings


def test_proxy_url_is_split_without_credentials_in_server() -> None:
    proxy = ProxySettings.from_url("socks5://user:secret@127.0.0.1:1080")

    assert proxy.server == "socks5://127.0.0.1:1080"
    assert proxy.username == "user"
    assert proxy.password == "secret"
    assert "secret" not in repr(proxy)


def test_account_password_is_hidden_from_repr() -> None:
    account = Account(id="account-1", email="user@example.test", password="secret")

    assert "secret" not in repr(account)


def test_config_rejects_more_than_ten_accounts(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "target_url": "examples/demo.html",
                "accounts": [
                    {"id": f"account-{index}", "email": f"user{index}@example.test", "password": "secret"}
                    for index in range(11)
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="at most 10"):
        load_config(config_path)

