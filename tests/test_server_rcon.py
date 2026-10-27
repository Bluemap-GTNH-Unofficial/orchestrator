import socket
import struct
import threading

import pytest

from orchestrator.rcon import RconError
from orchestrator.server import Server, ServerConfig


def _packet(request_id: int, packet_type: int, body: bytes) -> bytes:
    payload = struct.pack("<ii", request_id, packet_type) + body + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload


def _read_request(conn: socket.socket) -> tuple[int, bytes] | None:
    header = conn.recv(4, socket.MSG_WAITALL)
    if len(header) < 4:
        return None
    (length,) = struct.unpack("<i", header)
    data = conn.recv(length, socket.MSG_WAITALL)
    return struct.unpack("<i", data[:4])[0], data[8:-2]


def test_commands_share_one_connection_and_a_broken_one_is_replaced(tmp_path):
    listener = socket.create_server(("127.0.0.1", 0))
    connections = []

    def serve() -> None:
        with listener:
            while len(connections) < 2:
                conn, _ = listener.accept()
                connections.append(conn)
                with conn:
                    request_id, _ = _read_request(conn)  # login
                    conn.sendall(_packet(request_id, 2, b""))
                    while (request := _read_request(conn)) is not None:
                        request_id, body = request
                        if body == b"die":
                            break  # drop the connection without replying
                        conn.sendall(_packet(request_id, 0, b"re:" + body))

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    (tmp_path / ".rcon-password").write_text("pw\n")
    server = Server(ServerConfig(root=tmp_path, rcon_port=listener.getsockname()[1]))

    assert server.rcon("a") == ["re:a"]
    assert server.rcon("b", "c") == ["re:b", "re:c"]
    assert len(connections) == 1
    with pytest.raises(RconError, match="closed"):
        server.rcon("die")
    assert server.rcon("d") == ["re:d"]
    assert len(connections) == 2
    server.close_rcon()
    thread.join(5)
