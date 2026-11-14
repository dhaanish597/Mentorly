"""Fixed-host archive connections, resolved and pinned before any TCP connect.

No redirects, proxies, clone commands, credentials, or repository execution.
TLS still receives the original hostname from httpcore for SNI/certificate checks.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
import ipaddress
import socket
import ssl

import httpcore
import httpx
from httpcore._backends.anyio import AnyIOBackend

from .ingest import ImportFailure

ARCHIVE_HOSTS = frozenset({'codeload.github.com', 'gitlab.com'})
DNS_TIMEOUT = 5.0
Resolver = Callable[[str, int], Awaitable[list[str]]]


async def resolve_addresses(host: str, port: int) -> list[str]:
    records = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({record[4][0] for record in records})


def public_address(address: str) -> bool:
    try:
        value = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(value, ipaddress.IPv6Address) and (value.ipv4_mapped or value.sixtofour or value.teredo or '%' in address):
        return False
    return value.is_global and not any((value.is_multicast, value.is_reserved, value.is_unspecified, value.is_loopback, value.is_link_local))


class PublicArchiveBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, resolver: Resolver | None = None, backend: httpcore.AsyncNetworkBackend | None = None) -> None:
        self._resolver = resolver or resolve_addresses
        self._backend = backend or AnyIOBackend()

    async def connect_tcp(self, host: str, port: int, timeout: float | None = None,
                          local_address: str | None = None, socket_options: Iterable | None = None) -> httpcore.AsyncNetworkStream:
        if host not in ARCHIVE_HOSTS or port != 443 or local_address is not None:
            raise ImportFailure('unsupported archive connection')
        try:
            # This envelope also bounds resolution; the download has its own
            # total wallclock deadline encompassing connect, headers and body.
            async with asyncio.timeout(min(timeout, DNS_TIMEOUT) if timeout is not None else DNS_TIMEOUT):
                addresses = await self._resolver(host, port)
                if not addresses or not all(public_address(address) for address in addresses):
                    raise ImportFailure('archive address rejected')
                # Numeric IP prevents a second hostname lookup / DNS rebinding.
                return await self._backend.connect_tcp(addresses[0], port, timeout=timeout, socket_options=socket_options)
        except TimeoutError as exc:
            raise ImportFailure('archive connection timeout') from exc
        except OSError as exc:
            raise ImportFailure('archive address unavailable') from exc

    async def connect_unix_socket(self, path: str, timeout: float | None = None,
                                  socket_options: Iterable | None = None) -> httpcore.AsyncNetworkStream:
        raise ImportFailure('archive unix sockets forbidden')

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class PublicArchiveTransport(httpx.AsyncHTTPTransport):
    def __init__(self) -> None:
        # httpx 0.28's adapter has no network_backend argument. Its inspected
        # request/response/error adapter delegates to this httpcore public pool.
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(), network_backend=PublicArchiveBackend(),
            max_connections=1, max_keepalive_connections=0, retries=0,
        )
