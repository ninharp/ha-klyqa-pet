"""Shared fixtures: a real local aiohttp server stands in for devices and the cloud."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
import json
from typing import Any

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest


@dataclass
class Call:
    """One request the fake API received."""

    method: str
    path: str
    headers: dict[str, str]
    json: Any


@dataclass
class FakeApi:
    """Canned responses keyed by (METHOD, path); records every call.

    `add()` queues responses per route: with one queued response it is returned on every
    call, with several they are consumed in order (the last one sticks).
    """

    host: str
    port: int
    responses: dict[tuple[str, str], list[tuple[int, Any, float]]] = field(default_factory=dict)
    calls: list[Call] = field(default_factory=list)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def add(
        self,
        method: str,
        path: str,
        status: int = 200,
        payload: Any = None,
        body: str | None = None,
        delay: float = 0.0,
    ) -> None:
        """Queue a response; `payload` is sent as JSON, `body` as raw text."""
        content = body if body is not None else payload
        self.responses.setdefault((method.upper(), path), []).append((status, content, delay))

    def last_call(self) -> Call:
        return self.calls[-1]

    def calls_for(self, method: str, path: str) -> list[Call]:
        return [c for c in self.calls if c.method == method.upper() and c.path == path]


@pytest.fixture(autouse=True)
def _enable_sockets(socket_enabled: None) -> None:
    """Allow real localhost sockets.

    `pytest-homeassistant-custom-component` disables `socket.socket` for every test by
    default; these tests talk to a real local aiohttp server, so re-enable it here.
    """


@pytest.fixture
async def api(
    aiohttp_server: Callable[..., Awaitable[TestServer]],
) -> FakeApi:
    fake_holder: list[FakeApi] = []

    async def handler(request: web.Request) -> web.StreamResponse:
        fake = fake_holder[0]
        text = await request.text()
        try:
            payload = json.loads(text) if text else None
        except ValueError:
            payload = text
        fake.calls.append(Call(request.method, request.path, dict(request.headers), payload))
        queue = fake.responses.get((request.method, request.path))
        if not queue:
            return web.Response(
                status=404, text=f"no canned response for {request.method} {request.path}"
            )
        status, content, delay = queue.pop(0) if len(queue) > 1 else queue[0]
        if delay:
            await asyncio.sleep(delay)
        if isinstance(content, str):
            return web.Response(status=status, text=content)
        return web.json_response(content, status=status)

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    server = await aiohttp_server(app)
    fake = FakeApi(server.host, server.port)
    fake_holder.append(fake)
    return fake


@pytest.fixture
async def session() -> AsyncGenerator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client_session:
        yield client_session
