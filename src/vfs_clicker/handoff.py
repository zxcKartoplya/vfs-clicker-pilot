import asyncio
import re
import shutil
import socket
from dataclasses import dataclass, field
from pathlib import Path

from vfs_clicker.models import ProxySettings

__all__ = ["ChromeHandoffSession", "find_chrome_executable", "profile_path"]


@dataclass(slots=True)
class ChromeHandoffSession:
    chrome_path: Path
    profile_dir: Path
    target_url: str
    proxy: ProxySettings | None = field(default=None, repr=False)
    startup_timeout_seconds: float = 20
    _process: asyncio.subprocess.Process | None = field(default=None, init=False, repr=False)

    async def start(self) -> str:
        if self._process is not None:
            raise RuntimeError("Chrome handoff session is already running")
        if not self.chrome_path.is_file():
            raise FileNotFoundError(f"Google Chrome executable not found: {self.chrome_path}")
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.chmod(0o700)
        debugging_port = _available_port()
        self._process = await asyncio.create_subprocess_exec(
            *self._arguments(debugging_port),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            return await self._wait_for_endpoint(debugging_port)
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()

    async def __aenter__(self) -> str:
        return await self.start()

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        await self.close()

    def _arguments(self, debugging_port: int) -> tuple[str, ...]:
        arguments = [
            str(self.chrome_path),
            f"--user-data-dir={self.profile_dir}",
            f"--remote-debugging-port={debugging_port}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if self.proxy is not None:
            arguments.append(f"--proxy-server={self.proxy.server}")
        arguments.append(self.target_url)
        return tuple(arguments)

    async def _wait_for_endpoint(self, debugging_port: int) -> str:
        deadline = asyncio.get_running_loop().time() + self.startup_timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            if self._process is None or self._process.returncode is not None:
                raise RuntimeError("Google Chrome stopped before remote control became available")
            try:
                _reader, writer = await asyncio.open_connection("127.0.0.1", debugging_port)
            except OSError:
                await asyncio.sleep(0.1)
                continue
            writer.close()
            await writer.wait_closed()
            return f"http://127.0.0.1:{debugging_port}"
        raise TimeoutError("Google Chrome did not expose a remote control endpoint")


def find_chrome_executable() -> Path:
    candidates = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    executable = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    if executable is not None:
        return Path(executable)
    raise FileNotFoundError("Google Chrome executable was not found")


def profile_path(base_dir: Path, account_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "-", account_id).strip(".-")
    if not safe_id:
        raise ValueError("Account id cannot be converted to a Chrome profile name")
    return base_dir / safe_id


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]
