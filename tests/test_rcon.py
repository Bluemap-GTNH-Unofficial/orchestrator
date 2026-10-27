import socket
import struct
import threading

import pytest

from orchestrator.rcon import FRAGMENT_SIZE, RconClient, RconError


def _packet(request_id: int, packet_type: int, body: bytes) -> bytes:
    payload = struct.pack("<ii", request_id, packet_type) + body + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload


def _read_request(conn: socket.socket) -> tuple[int, int, bytes]:
    (length,) = struct.unpack("<i", conn.recv(4, socket.MSG_WAITALL))
    data = conn.recv(length, socket.MSG_WAITALL)
    request_id, packet_type = struct.unpack("<ii", data[:8])
    return request_id, packet_type, data[8:-2]


def _serve(handler) -> tuple[int, threading.Thread]:
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]

    def run() -> None:
        conn, _ = listener.accept()
        with conn, listener:
            handler(conn)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return port, thread


def _login_ok(conn: socket.socket, password: bytes = b"pw") -> None:
    request_id, packet_type, body = _read_request(conn)
    assert packet_type == 3
    conn.sendall(_packet(request_id if body == password else -1, 2, b""))


def test_reassembles_reply_split_at_fragment_size():
    long_reply = b"a" * FRAGMENT_SIZE + b"b" * 10

    def handler(conn: socket.socket) -> None:
        _login_ok(conn)
        request_id, _, _ = _read_request(conn)
        conn.sendall(_packet(request_id, 0, long_reply[:FRAGMENT_SIZE]))
        conn.sendall(_packet(request_id, 0, long_reply[FRAGMENT_SIZE:]))

    port, thread = _serve(handler)
    with RconClient("127.0.0.1", port, "pw", timeout=5) as client:
        assert client.command("dump") == long_reply.decode("latin-1")
    thread.join(5)


def test_reply_of_exactly_fragment_size_ends_after_quiet_window():
    def handler(conn: socket.socket) -> None:
        _login_ok(conn)
        request_id, _, _ = _read_request(conn)
        conn.sendall(_packet(request_id, 0, b"x" * FRAGMENT_SIZE))
        conn.recv(1)  # keep the socket open until the client closes it

    port, thread = _serve(handler)
    with RconClient("127.0.0.1", port, "pw", timeout=5, continuation_timeout=0.1) as client:
        assert client.command("x") == "x" * FRAGMENT_SIZE
    thread.join(5)


def test_decodes_section_sign_as_latin1():
    def handler(conn: socket.socket) -> None:
        _login_ok(conn)
        request_id, _, _ = _read_request(conn)
        conn.sendall(_packet(request_id, 0, b"\xa7aOK"))

    port, thread = _serve(handler)
    with RconClient("127.0.0.1", port, "pw", timeout=5) as client:
        assert client.command("x") == "\u00a7aOK"
    thread.join(5)


def test_wrong_password_raises():
    port, thread = _serve(_login_ok)
    with pytest.raises(RconError, match="authentication"):
        RconClient("127.0.0.1", port, "wrong", timeout=5).connect()
    thread.join(5)
