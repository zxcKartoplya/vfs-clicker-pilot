from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import pproxy

from vfs_clicker.models import ProxySettings

__all__ = ["AuthenticatedSocksBridge"]


@dataclass(slots=True)
class AuthenticatedSocksBridge:
    upstream: ProxySettings = field(repr=False)
    _handler: Any = field(default=None, init=False, repr=False)
    _local_proxy: ProxySettings | None = field(default=None, init=False, repr=False)

    async def start(self) -> ProxySettings:
        if self._handler is not None or self._local_proxy is not None:
            raise RuntimeError("Proxy bridge is already running")
        remote_uri = self._build_remote_uri()
        server = pproxy.Server("socks5://127.0.0.1:0")
        remote = pproxy.Connection(remote_uri)
        self._handler = await server.start_server({"rserver": [remote], "verbose": lambda *_: None})
        port = self._handler.sockets[0].getsockname()[1]
        self._local_proxy = ProxySettings(server=f"socks5://127.0.0.1:{port}")
        return self._local_proxy

    async def close(self) -> None:
        if self._handler is None:
            return
        self._handler.close()
        await self._handler.wait_closed()
        self._handler = None
        self._local_proxy = None

    async def __aenter__(self) -> ProxySettings:
        return await self.start()

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        await self.close()

    def _build_remote_uri(self) -> str:
        parsed = urlsplit(self.upstream.server)
        if parsed.scheme != "socks5" or parsed.hostname is None or parsed.port is None:
            raise ValueError("Authenticated bridge requires a SOCKS5 upstream proxy")
        if self.upstream.username is None or self.upstream.password is None:
            raise ValueError("Authenticated bridge requires proxy username and password")
        if ":" in self.upstream.username or "#" in self.upstream.username or "#" in self.upstream.password:
            raise ValueError("Proxy credentials contain characters unsupported by the bridge")
        return (
            f"socks5://{parsed.hostname}:{parsed.port}"
            f"#{self.upstream.username}:{self.upstream.password}"
        )
