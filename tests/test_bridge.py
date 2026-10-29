import asyncio
import socket

import pproxy
import pytest

from vfs_clicker.bridge import AuthenticatedSocksBridge
from vfs_clicker.models import Account, ProxySettings
from vfs_clicker.proxies import BridgedProxyProvider


@pytest.mark.asyncio
async def test_bridge_forwards_through_authenticated_socks5_upstream() -> None:
    target_server = await asyncio.start_server(_echo_until_closed, "127.0.0.1", 0)
    target_port = target_server.sockets[0].getsockname()[1]

    upstream = pproxy.Server("socks5://127.0.0.1:0#bridge-user:bridge-pass")
    upstream_handler = await upstream.start_server({"rserver": [], "verbose": lambda *_: None})
    upstream_port = upstream_handler.sockets[0].getsockname()[1]
    upstream_proxy = ProxySettings(
        server=f"socks5://127.0.0.1:{upstream_port}",
        username="bridge-user",
        password="bridge-pass",
    )

    bridge = AuthenticatedSocksBridge(upstream_proxy)
    try:
        local_proxy = await bridge.start()
        local_port = url_port(local_proxy.server)
        reader, writer = await asyncio.open_connection("127.0.0.1", local_port)
        writer.write(b"\x05\x01\x00")
        await writer.drain()
        assert await reader.readexactly(2) == b"\x05\x00"

        request = b"\x05\x01\x00\x01" + socket.inet_aton("127.0.0.1") + target_port.to_bytes(2, "big")
        writer.write(request)
        await writer.drain()
        reply = await reader.readexactly(10)
        assert reply[:2] == b"\x05\x00"

        writer.write(b"bridge-ok")
        await writer.drain()
        assert await reader.readexactly(9) == b"bridge-ok"
        assert bridge._connection_tasks

        await bridge.close()

        assert not bridge._connection_tasks
        assert await reader.read() == b""
        writer.close()
        await writer.wait_closed()
    finally:
        await bridge.close()
        upstream_handler.close()
        await upstream_handler.wait_closed()
        target_server.close()
        await target_server.wait_closed()


async def _echo_until_closed(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(1024):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


def url_port(value: str) -> int:
    return int(value.rsplit(":", 1)[1])


@pytest.mark.asyncio
async def test_provider_hides_upstream_credentials_from_playwright() -> None:
    upstream = ProxySettings(
        server="socks5://127.0.0.1:9",
        username="bridge-user",
        password="bridge-pass",
    )
    provider = BridgedProxyProvider((upstream,))

    await provider.start()
    try:
        effective = await provider.acquire(
            Account(id="account-1", email="user@example.test", password="secret"),
            0,
        )

        assert effective is not None
        assert effective.server.startswith("socks5://127.0.0.1:")
        assert effective.username is None
        assert effective.password is None
        assert effective.as_playwright_options() == {"server": effective.server}
    finally:
        await provider.close()
