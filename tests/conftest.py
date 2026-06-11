"""Shared test fixtures (plan §10.2).

Phase 0 establishes the socket guard — the rest (FakeChatGenerator, fakeredis,
stub Qdrant/Voyage, SSE collector) lands with the Phase 1 suite.
"""

from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def _no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any unit test that opens a real network connection.

    Unit tests must be hermetic — every LLM / vector / Redis call is faked.
    Tests marked ``integration`` or ``live`` legitimately use the network and are
    exempt. (In-process ASGI transport and fakeredis never hit a real socket, so
    they pass straight through.)
    """
    if request.node.get_closest_marker("integration") or request.node.get_closest_marker("live"):
        return

    def _blocked(*_args: object, **_kwargs: object):  # noqa: ANN202
        raise RuntimeError(
            "Network access blocked in a unit test. Mock the call, or mark the "
            "test @pytest.mark.integration / @pytest.mark.live."
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
