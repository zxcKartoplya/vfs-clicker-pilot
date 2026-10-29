from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import unquote, urlsplit

__all__ = ["Account", "ProxySettings", "SessionResult", "SessionStatus"]


@dataclass(frozen=True, slots=True)
class Account:
    id: str
    email: str
    password: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProxySettings:
    server: str
    username: str | None = None
    password: str | None = field(default=None, repr=False)

    @classmethod
    def from_url(cls, value: str) -> "ProxySettings":
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https", "socks5"}:
            raise ValueError("Proxy scheme must be http, https, or socks5")
        if parsed.hostname is None or parsed.port is None:
            raise ValueError("Proxy URL must contain host and port")
        server = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        username = unquote(parsed.username) if parsed.username else None
        password = unquote(parsed.password) if parsed.password else None
        return cls(server=server, username=username, password=password)

    def as_playwright_options(self) -> dict[str, str]:
        options = {"server": self.server}
        if self.username is not None:
            options["username"] = self.username
        if self.password is not None:
            options["password"] = self.password
        return options


class SessionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    MANUAL_ACTION_REQUIRED = "manual_action_required"


@dataclass(frozen=True, slots=True)
class SessionResult:
    account_id: str
    status: SessionStatus
    detail: str

