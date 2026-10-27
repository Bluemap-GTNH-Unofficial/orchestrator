"""Minimal RCON client tuned for Minecraft 1.7.10 servers.

1.7.10 quirks handled here:
- Replies are written with ``DataOutputStream.writeBytes`` (low byte of each char), so they
  are decoded as Latin-1, never UTF-8.
- The server reads each request with a single ``read()``; pipelining two packets drops the
  connection. Exactly one request is in flight at a time.
- Long replies are split into 4096-character fragments without an end marker. A fragment
  shorter than 4096 ends the reply; a full-size fragment is followed by a short read window.
"""

from __future__ import annotations

import socket
import struct
from types import TracebackType

TYPE_COMMAND = 2
TYPE_LOGIN = 3
FRAGMENT_SIZE = 4096
MAX_COMMAND_BYTES = 1446


class RconError(Exception):
    pass


class RconClient:
    def __init__(
        self,
        host: str,
        port: int,
        password: str,
        timeout: float = 600.0,
        continuation_timeout: float = 0.3,
    ) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._timeout = timeout
        self._continuation_timeout = continuation_timeout
        self._sock: socket.socket | None = None
        self._next_id = 1

    def __enter__(self) -> RconClient:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def connect(self) -> None:
        self._sock = socket.create_connection((self._host, self._port), timeout=self._timeout)
        request_id = self._send(TYPE_LOGIN, self._password)
        response_id, _, _ = self._read_packet()
        if response_id == -1 or response_id != request_id:
            self.close()
            raise RconError("RCON authentication failed")

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def command(self, command: str) -> str:
        request_id = self._send(TYPE_COMMAND, command)
        fragments: list[str] = []
        response_id, _, payload = self._read_packet()
        if response_id != request_id:
            raise RconError(f"unexpected response id {response_id}, expected {request_id}")
        fragments.append(payload)
        while len(payload) >= FRAGMENT_SIZE:
            continuation = self._read_continuation()
            if continuation is None:
                break
            response_id, _, payload = continuation
            fragments.append(payload)
        return "".join(fragments)

    def _send(self, packet_type: int, body: str) -> int:
        sock = self._require_socket()
        encoded = body.encode("latin-1")
        if len(encoded) > MAX_COMMAND_BYTES:
            raise RconError(f"RCON payload of {len(encoded)} bytes exceeds {MAX_COMMAND_BYTES}")
        request_id = self._next_id
        self._next_id += 1
        payload = struct.pack("<ii", request_id, packet_type) + encoded + b"\x00\x00"
        sock.sendall(struct.pack("<i", len(payload)) + payload)
        return request_id

    def _read_continuation(self) -> tuple[int, int, str] | None:
        sock = self._require_socket()
        sock.settimeout(self._continuation_timeout)
        try:
            return self._read_packet()
        except TimeoutError:
            return None
        finally:
            sock.settimeout(self._timeout)

    def _read_packet(self) -> tuple[int, int, str]:
        (length,) = struct.unpack("<i", self._read_exact(4))
        data = self._read_exact(length)
        response_id, packet_type = struct.unpack("<ii", data[:8])
        return response_id, packet_type, data[8:-2].decode("latin-1")

    def _read_exact(self, n: int) -> bytes:
        sock = self._require_socket()
        chunks = bytearray()
        while len(chunks) < n:
            chunk = sock.recv(n - len(chunks))
            if not chunk:
                raise RconError("RCON connection closed by server")
            chunks += chunk
        return bytes(chunks)

    def _require_socket(self) -> socket.socket:
        if self._sock is None:
            raise RconError("RCON client is not connected")
        return self._sock
