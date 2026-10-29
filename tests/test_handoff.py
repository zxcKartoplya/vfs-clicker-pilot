from pathlib import Path

import pytest

from vfs_clicker.handoff import ChromeHandoffSession, profile_path
from vfs_clicker.models import ProxySettings


def test_handoff_arguments_use_persistent_profile_without_automation_flag(tmp_path: Path) -> None:
    chrome_path = tmp_path / "chrome"
    profile_dir = tmp_path / "profiles" / "account-1"
    session = ChromeHandoffSession(
        chrome_path=chrome_path,
        profile_dir=profile_dir,
        target_url="https://example.test/login",
        proxy=ProxySettings(server="socks5://127.0.0.1:9000"),
    )

    arguments = session._arguments(9333)

    assert arguments[0] == str(chrome_path)
    assert f"--user-data-dir={profile_dir}" in arguments
    assert "--remote-debugging-port=9333" in arguments
    assert "--proxy-server=socks5://127.0.0.1:9000" in arguments
    assert "--enable-automation" not in arguments
    assert arguments[-1] == "https://example.test/login"


def test_profile_path_sanitizes_account_id(tmp_path: Path) -> None:
    assert profile_path(tmp_path, "account/one") == tmp_path / "account-one"


@pytest.mark.asyncio
async def test_handoff_session_starts_and_stops_managed_process(tmp_path: Path) -> None:
    chrome_path = tmp_path / "fake-chrome"
    chrome_path.write_text(
        """#!/usr/bin/env python3
import signal
import socket
import sys

port = int(next(item.split("=", 1)[1] for item in sys.argv if item.startswith("--remote-debugging-port=")))
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind(("127.0.0.1", port))
server.listen()
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
while True:
    connection, _ = server.accept()
    connection.close()
""",
        encoding="utf-8",
    )
    chrome_path.chmod(0o700)
    session = ChromeHandoffSession(
        chrome_path=chrome_path,
        profile_dir=tmp_path / "profile",
        target_url="https://example.test/login",
        startup_timeout_seconds=2,
    )

    endpoint = await session.start()

    assert endpoint.startswith("http://127.0.0.1:")
    assert session._process is not None

    await session.close()

    assert session._process is None
