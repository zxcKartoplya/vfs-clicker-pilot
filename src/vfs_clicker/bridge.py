import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from vfs_clicker.models import ProxySettings

__all__ = ["AuthenticatedSocksBridge"]


@dataclass(slots=True)
class AuthenticatedSocksBridge:
    upstream: ProxySettings = field(repr=False)
    _handler: asyncio.AbstractServer | None = field(default=None, init=False, repr=False)
    _connection_tasks: set[asyncio.Task[None]] = field(
        default_factory=set,
        init=False,
        repr=False,
    )
    _local_proxy: ProxySettings | None = field(default=None, init=False, repr=False)

    async def start(self) -> ProxySettings:
        if self._handler is not None or self._local_proxy is not None:
            raise RuntimeError("Proxy bridge is already running")
        self._validate_upstream()
        self._handler = await asyncio.start_server(self._schedule_client, "127.0.0.1", 0)
        port = self._handler.sockets[0].getsockname()[1]
        self._local_proxy = ProxySettings(server=f"socks5://127.0.0.1:{port}")
        return self._local_proxy

    async def close(self) -> None:
        if self._handler is not None:
            self._handler.close()
            await asyncio.sleep(0)
        while self._connection_tasks:
            tasks = tuple(self._connection_tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._handler is not None:
            await self._handler.wait_closed()
            self._handler = None
        self._local_proxy = None

    async def __aenter__(self) -> ProxySettings:
        return await self.start()

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        await self.close()

    def _schedule_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        task = asyncio.create_task(self._handle_client(reader, writer))
        self._connection_tasks.add(task)
        task.add_done_callback(self._connection_tasks.discard)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        upstream_writer: asyncio.StreamWriter | None = None
        connected = False
        try:
            destination = await self._accept_client(reader, writer)
            upstream_reader, upstream_writer, reply = await self._connect_upstream(destination)
            writer.write(reply)
            await writer.drain()
            connected = True
            await self._relay(reader, writer, upstream_reader, upstream_writer)
        except asyncio.CancelledError:
            raise
        except Exception:
            if not connected and not writer.is_closing():
                writer.write(b"\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00")
                with suppress(Exception):
                    await writer.drain()
        finally:
            await self._close_writer(upstream_writer)
            await self._close_writer(writer)

    async def _accept_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> bytes:
        version, method_count = await reader.readexactly(2)
        methods = await reader.readexactly(method_count)
        if version != 5 or 0 not in methods:
            writer.write(b"\x05\xff")
            await writer.drain()
            raise RuntimeError("Browser did not offer unauthenticated SOCKS5")
        writer.write(b"\x05\x00")
        await writer.drain()

        version, command, reserved, address_type = await reader.readexactly(4)
        if version != 5 or command != 1 or reserved != 0:
            raise RuntimeError("Unsupported browser SOCKS5 request")
        address = await self._read_address(reader, address_type)
        port = await reader.readexactly(2)
        return bytes((address_type,)) + address + port

    async def _connect_upstream(
        self,
        destination: bytes,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, bytes]:
        parsed = urlsplit(self.upstream.server)
        reader, writer = await asyncio.open_connection(parsed.hostname, parsed.port)
        try:
            writer.write(b"\x05\x01\x02")
            await writer.drain()
            if await reader.readexactly(2) != b"\x05\x02":
                raise RuntimeError("Upstream proxy rejected username authentication")

            username = self.upstream.username.encode()
            password = self.upstream.password.encode()
            writer.write(
                b"\x01"
                + bytes((len(username),))
                + username
                + bytes((len(password),))
                + password
            )
            await writer.drain()
            auth_version, auth_status = await reader.readexactly(2)
            if auth_version != 1 or auth_status != 0:
                raise RuntimeError("Upstream proxy authentication failed")

            writer.write(b"\x05\x01\x00" + destination)
            await writer.drain()
            header = await reader.readexactly(4)
            address = await self._read_address(reader, header[3])
            port = await reader.readexactly(2)
            if header[0] != 5 or header[1] != 0:
                raise RuntimeError(f"Upstream proxy connection failed with status {header[1]}")
            return reader, writer, header + address + port
        except BaseException:
            await self._close_writer(writer)
            raise

    async def _relay(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        upstream_reader: asyncio.StreamReader,
        upstream_writer: asyncio.StreamWriter,
    ) -> None:
        tasks = {
            asyncio.create_task(self._pipe(client_reader, upstream_writer)),
            asyncio.create_task(self._pipe(upstream_reader, client_writer)),
        }
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _pipe(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        while data := await reader.read(65_536):
            writer.write(data)
            await writer.drain()

    async def _read_address(self, reader: asyncio.StreamReader, address_type: int) -> bytes:
        if address_type == 1:
            return await reader.readexactly(4)
        if address_type == 3:
            length = await reader.readexactly(1)
            return length + await reader.readexactly(length[0])
        if address_type == 4:
            return await reader.readexactly(16)
        raise RuntimeError(f"Unsupported SOCKS5 address type {address_type}")

    async def _close_writer(self, writer: asyncio.StreamWriter | None) -> None:
        if writer is None:
            return
        writer.close()
        with suppress(Exception):
            await writer.wait_closed()

    def _validate_upstream(self) -> None:
        parsed = urlsplit(self.upstream.server)
        if parsed.scheme != "socks5" or parsed.hostname is None or parsed.port is None:
            raise ValueError("Authenticated bridge requires a SOCKS5 upstream proxy")
        if self.upstream.username is None or self.upstream.password is None:
            raise ValueError("Authenticated bridge requires proxy username and password")
        if not 1 <= len(self.upstream.username.encode()) <= 255:
            raise ValueError("Proxy username must contain 1-255 bytes")
        if not 1 <= len(self.upstream.password.encode()) <= 255:
            raise ValueError("Proxy password must contain 1-255 bytes")
