import socket

import pytest


def test_default_test_suite_blocks_network_connections() -> None:
    with pytest.raises(AssertionError, match="tests cannot access the network"):
        socket.create_connection(("example.invalid", 443))
