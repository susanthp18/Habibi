"""Pinned public-address transport for reviewed customer HTTP tools."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
from typing import Any

import httpcore
import httpx
from httpcore._backends.auto import AutoBackend
from httpcore._backends.base import AsyncNetworkBackend, AsyncNetworkStream


class PublicNetworkBackend(AsyncNetworkBackend):
    """Resolve on connect, reject every non-public answer, then dial that IP."""

    def __init__(self) -> None:
        self._backend = AutoBackend()

    async def connect_tcp(self, host: str, port: int, timeout: float | None = None,
                          local_address: str | None = None,
                          socket_options: Any = None) -> AsyncNetworkStream:
        answers = await asyncio.to_thread(
            socket.getaddrinfo, host, port, type=socket.SOCK_STREAM,
        )
        if not answers or any(
            not ipaddress.ip_address(answer[4][0]).is_global for answer in answers
        ):
            raise ValueError("tool destination resolved to a non-public address")
        address = answers[0][4][0]
        return await self._backend.connect_tcp(
            address, port, timeout=timeout, local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(self, path: str, timeout: float | None = None,
                                  socket_options: Any = None) -> AsyncNetworkStream:
        raise ValueError("Unix sockets are not permitted for external tools")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class PublicHTTPTransport(httpx.AsyncHTTPTransport):
    """Keep the approved hostname for TLS while pinning the dialled IP."""

    def __init__(self) -> None:
        super().__init__()
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=PublicNetworkBackend(),
            max_connections=16, max_keepalive_connections=4,
            http1=True, http2=False, retries=0,
        )
