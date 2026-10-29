from typing import Protocol

from vfs_clicker.bridge import AuthenticatedSocksBridge
from vfs_clicker.models import Account, ProxySettings, SessionResult

__all__ = ["BridgedProxyProvider", "ProxyProvider", "StaticProxyProvider"]


class ProxyProvider(Protocol):
    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def acquire(self, account: Account, index: int) -> ProxySettings | None: ...

    async def release(self, account: Account, proxy: ProxySettings | None, result: SessionResult) -> None: ...


class StaticProxyProvider:
    def __init__(self, proxies: tuple[ProxySettings, ...]) -> None:
        self._proxies = proxies

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def acquire(self, account: Account, index: int) -> ProxySettings | None:
        if not self._proxies:
            return None
        return self._proxies[index % len(self._proxies)]

    async def release(self, account: Account, proxy: ProxySettings | None, result: SessionResult) -> None:
        return None


class BridgedProxyProvider:
    def __init__(self, proxies: tuple[ProxySettings, ...]) -> None:
        self._upstream_proxies = proxies
        self._effective_proxies: tuple[ProxySettings, ...] = ()
        self._bridges: list[AuthenticatedSocksBridge] = []

    async def start(self) -> None:
        if self._effective_proxies or self._bridges:
            raise RuntimeError("Proxy provider is already running")
        effective: list[ProxySettings] = []
        try:
            for proxy in self._upstream_proxies:
                if proxy.server.startswith("socks5://") and proxy.username is not None:
                    bridge = AuthenticatedSocksBridge(proxy)
                    effective.append(await bridge.start())
                    self._bridges.append(bridge)
                else:
                    effective.append(proxy)
        except Exception:
            await self.close()
            raise
        self._effective_proxies = tuple(effective)

    async def close(self) -> None:
        for bridge in reversed(self._bridges):
            await bridge.close()
        self._bridges.clear()
        self._effective_proxies = ()

    async def acquire(self, account: Account, index: int) -> ProxySettings | None:
        if not self._effective_proxies:
            return None
        return self._effective_proxies[index % len(self._effective_proxies)]

    async def release(self, account: Account, proxy: ProxySettings | None, result: SessionResult) -> None:
        return None

