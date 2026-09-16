import socket

import pytest


@pytest.fixture(autouse=True)
def block_unapproved_network_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail every test that tries to open a network connection."""

    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "tests cannot access the network; use an explicit, user-approved smoke command"
        )

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
