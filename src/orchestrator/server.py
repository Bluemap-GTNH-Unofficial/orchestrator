"""Lifecycle of a headless GTNH server directory: properties, start, readiness, stop."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.rcon import RconClient, RconError

JAVA = "java@temurin-25.0.5+8.0.LTS"
READY_PATTERN = re.compile(r"RCON running on ")
FAILURE_PATTERN = re.compile(r"Encountered an unexpected exception|The state engine was in incorrect state")
PID_FILE = ".orchestrator.pid"
LOG_FILE = "orchestrator-console.log"


class ServerError(Exception):
    pass


@dataclass(frozen=True)
class ServerConfig:
    root: Path
    server_port: int = 25565
    rcon_port: int = 25575
    xms: str = "6G"
    xmx: str = "12G"
    level_name: str = "World"
    level_seed: str = "1710"
    level_type: str = "rwg"
    extra_properties: dict[str, str] = field(default_factory=dict)

    @property
    def password_file(self) -> Path:
        return self.root / ".rcon-password"

    def password(self) -> str:
        return self.password_file.read_text(encoding="utf-8").strip()

    def properties(self) -> dict[str, str]:
        props = {
            "server-ip": "127.0.0.1",
            "server-port": str(self.server_port),
            "enable-rcon": "true",
            "rcon.port": str(self.rcon_port),
            "rcon.password": self.password(),
            "online-mode": "false",
            "white-list": "false",
            "level-name": self.level_name,
            "level-seed": self.level_seed,
            "level-type": self.level_type,
        }
        props.update(self.extra_properties)
        return props


def render_properties(existing: str, overrides: dict[str, str]) -> str:
    """Replace keys in a server.properties text, append missing ones, keep everything else."""
    remaining = dict(overrides)
    lines = []
    for line in existing.splitlines():
        key, sep, _ = line.partition("=")
        if sep and not line.lstrip().startswith("#") and key in remaining:
            lines.append(f"{key}={remaining.pop(key)}")
        else:
            lines.append(line)
    lines.extend(f"{key}={value}" for key, value in remaining.items())
    return "\n".join(lines) + "\n"


class Server:
    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self._proc: subprocess.Popen[bytes] | None = None
        self._rcon: RconClient | None = None

    @property
    def root(self) -> Path:
        return self.config.root

    def pid(self) -> int | None:
        """PID of the running server, whether started by this process or an earlier invocation."""
        pid_file = self.root / PID_FILE
        if self._proc is not None and self._proc.poll() is not None:
            self._proc = None
            pid_file.unlink(missing_ok=True)
            return None
        if not pid_file.exists():
            return None
        pid = int(pid_file.read_text().strip())
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pid_file.unlink()
            return None
        return pid

    def write_properties(self) -> None:
        path = self.root / "server.properties"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(render_properties(existing, self.config.properties()), encoding="utf-8")
        (self.root / "eula.txt").write_text("eula=true\n", encoding="utf-8")

    def start(self, timeout: float = 900.0) -> None:
        if self.pid() is not None:
            raise ServerError(f"server already running (pid {self.pid()})")
        if not self.config.password_file.exists():
            raise ServerError(f"missing {self.config.password_file}; create it with `openssl rand -hex 16`")
        self.write_properties()
        log_path = self.root / LOG_FILE
        cmd = [
            "mise", "exec", JAVA, "--", "java",
            f"-Xms{self.config.xms}", f"-Xmx{self.config.xmx}",
            "-XX:+UseCompactObjectHeaders", "-XX:+UseZGC",
            "-Dfml.readTimeout=180", "-Dfml.queryResult=confirm", "-Duser.language=en",
            "@java9args.txt", "-jar", "lwjgl3ify-forgePatches.jar", "nogui",
        ]  # fmt: skip
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                cmd,
                cwd=self.root,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self._proc = proc
        (self.root / PID_FILE).write_text(str(proc.pid))
        self._wait_ready(proc, log_path, timeout)

    def _wait_ready(self, proc: subprocess.Popen[bytes], log_path: Path, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            if READY_PATTERN.search(text):
                return
            if proc.poll() is not None:
                raise ServerError(f"server exited with {proc.returncode} during startup; see {log_path}")
            if FAILURE_PATTERN.search(text):
                os.killpg(proc.pid, signal.SIGKILL)
                raise ServerError(f"server failed to start; see {log_path}")
            time.sleep(1.0)
        os.killpg(proc.pid, signal.SIGKILL)
        raise ServerError(f"server not ready after {timeout:.0f}s; killed; see {log_path}")

    def stop(self, timeout: float = 300.0) -> None:
        pid = self.pid()
        if pid is None:
            return
        try:
            self.rcon("stop")
        except (OSError, RconError):
            # RCON is gone: the server crashed or is shutting down already
            self._signal_group(pid, signal.SIGTERM)
        finally:
            self.close_rcon()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.pid() is None:
                return
            time.sleep(1.0)
        self._signal_group(pid, signal.SIGKILL)
        raise ServerError(f"server did not stop within {timeout:.0f}s; killed pid {pid}")

    def _signal_group(self, pid: int, sig: signal.Signals) -> None:
        try:
            os.killpg(pid, sig)
        except (ProcessLookupError, PermissionError):
            # already exited; macOS reports EPERM for a group whose leader is a zombie
            pass

    def latest_crash_report(self, since: float) -> Path | None:
        reports = [p for p in (self.root / "crash-reports").glob("crash-*.txt") if p.stat().st_mtime >= since]
        return max(reports, key=lambda p: p.stat().st_mtime, default=None)

    def rcon_client(self) -> RconClient:
        return RconClient("127.0.0.1", self.config.rcon_port, self.config.password())

    def rcon(self, *commands: str) -> list[str]:
        """Sends commands over one RCON connection that is kept open between calls (a scene sends thousands of
        commands; a connection per command occasionally got reset by the 1.7.10 RCON listener). The connection is
        dropped on any error, so the next call reconnects; a failed command is never resent."""
        replies = []
        for command in commands:
            if self._rcon is None:
                client = self.rcon_client()
                client.connect()
                self._rcon = client
            try:
                replies.append(self._rcon.command(command))
            except (OSError, RconError):
                self.close_rcon()
                raise
        return replies

    def close_rcon(self) -> None:
        if self._rcon is not None:
            self._rcon.close()
            self._rcon = None

    def bmh(self, *args: str | int) -> dict:
        """Run a `bmh` harness subcommand and return its JSON payload."""
        (reply,) = self.rcon("bmh " + " ".join(str(a) for a in args))
        status, _, payload = reply.strip().partition(" ")
        if status == "OK":
            return json.loads(payload) if payload else {}
        raise ServerError(f"bmh {' '.join(map(str, args))}: {reply.strip()}")

    def te_nbt(self, dim: int, x: int, y: int, z: int, patch: dict | str, file: str = "te-nbt") -> dict:
        """`bmh te-nbt`: ``patch`` is a JSON patch object (see the harness README) or an SNBT string; returns the
        tile entity's NBT afterwards."""
        name = f"{file}.snbt" if isinstance(patch, str) else f"{file}.json"
        path = self.root / "bmh-out" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(patch if isinstance(patch, str) else json.dumps(patch), encoding="utf-8")
        return self.bmh("te-nbt", dim, x, y, z, name)

    def use(self, dim: int, x: int, y: int, z: int, side: str | int, item: str, meta: int = 0,
            yaw: float | None = None, count: int = 1, tag: dict | str | None = None) -> dict:  # fmt: skip
        """`bmh use`: right-click face ``side`` of block x/y/z with ``count`` x ``item:meta``; ``yaw`` defaults to
        looking at the face, as in the harness. ``tag`` (JSON-patch dict or SNBT string, typed as for te-nbt) becomes
        the item's NBT."""
        args: list[str | int | float] = ["use", dim, x, y, z, side, item, meta]
        if yaw is not None or count != 1:
            face = {"5": "EAST", "4": "WEST", "3": "SOUTH"}.get(str(side), str(side).upper())
            args.append(yaw if yaw is not None else {"EAST": 90, "WEST": 270, "SOUTH": 180}.get(face, 0))
        if count != 1:
            args.append(count)
        if tag is not None:
            name = "use-tag.snbt" if isinstance(tag, str) else "use-tag.json"
            path = self.root / "bmh-out" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(tag if isinstance(tag, str) else json.dumps(tag), encoding="utf-8")
            args += ["--tag", name]
        return self.bmh(*args)
