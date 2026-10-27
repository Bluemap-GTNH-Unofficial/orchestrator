"""`orch` command line: server lifecycle, RCON, bmh harness, world snapshots, scenes."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from orchestrator.server import Server, ServerConfig, ServerError

DEFAULT_SERVER = "gtnh-2.9.0-RC-2"


def workspace() -> Path:
    env = os.environ.get("BMGTNH_WORKSPACE")
    # src/orchestrator/cli.py -> orchestrator project -> testing -> BlueMap-GTNH -> workspace
    return Path(env) if env else Path(__file__).resolve().parents[5]


def snapshots_dir() -> Path:
    return workspace() / "worlds"


def make_server(args: argparse.Namespace) -> Server:
    root = workspace() / "servers" / args.server
    if not root.is_dir():
        raise ServerError(f"server directory {root} does not exist")
    return Server(
        ServerConfig(
            root=root,
            server_port=args.port,
            rcon_port=args.rcon_port,
            level_name=args.level,
            level_type=args.level_type,
            level_seed=args.seed,
            xmx=args.xmx,
        )
    )


def cmd_start(args: argparse.Namespace) -> None:
    server = make_server(args)
    server.start(timeout=args.timeout)
    print(f"started pid {server.pid()} level {args.level}")


def cmd_stop(args: argparse.Namespace) -> None:
    make_server(args).stop()
    print("stopped")


def cmd_status(args: argparse.Namespace) -> None:
    pid = make_server(args).pid()
    print(f"running pid {pid}" if pid else "stopped")


def cmd_rcon(args: argparse.Namespace) -> None:
    for reply in make_server(args).rcon(*args.commands):
        print(reply)


def cmd_bmh(args: argparse.Namespace) -> None:
    print(json.dumps(make_server(args).bmh(*args.args)))


def _require_stopped(server: Server) -> None:
    if server.pid() is not None:
        raise ServerError("stop the server before touching world folders")


def cmd_snapshot(args: argparse.Namespace) -> None:
    server = make_server(args)
    _require_stopped(server)
    src = server.root / args.level
    dst = snapshots_dir() / args.name
    if dst.exists():
        raise ServerError(f"snapshot {dst} already exists")
    shutil.copytree(src, dst)
    print(f"saved {src} -> {dst}")


def cmd_restore(args: argparse.Namespace) -> None:
    server = make_server(args)
    _require_stopped(server)
    src = snapshots_dir() / args.name
    dst = server.root / args.level
    if not src.is_dir():
        raise ServerError(f"no snapshot {src}")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    print(f"restored {src} -> {dst}")


def cmd_delete_level(args: argparse.Namespace) -> None:
    server = make_server(args)
    _require_stopped(server)
    target = server.root / args.level
    if target.exists():
        shutil.rmtree(target)
    print(f"deleted {target}")


def cmd_snapshots(_: argparse.Namespace) -> None:
    if snapshots_dir().is_dir():
        for p in sorted(snapshots_dir().iterdir()):
            print(p.name)


def cmd_scene(args: argparse.Namespace) -> None:
    from orchestrator import scenes

    out = workspace() / "out" / "scenes" / args.name
    result = scenes.run(args.name, make_server(args), out, snapshots_dir() / args.name)
    print(json.dumps(result, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orch", description=__doc__)
    parser.add_argument("--server", default=DEFAULT_SERVER, help="directory under <workspace>/servers")
    parser.add_argument("--port", type=int, default=25565)
    parser.add_argument("--rcon-port", type=int, default=25575)
    parser.add_argument("--level", default="World", help="level-name (world folder)")
    parser.add_argument("--level-type", default="rwg", help="rwg | FLAT | DEFAULT")
    parser.add_argument("--seed", default="1710")
    parser.add_argument("--xmx", default="12G")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("start", help="start server headless and wait for RCON")
    p.add_argument("--timeout", type=float, default=900.0)
    p.set_defaults(func=cmd_start)
    sub.add_parser("stop", help="stop via RCON").set_defaults(func=cmd_stop)
    sub.add_parser("status").set_defaults(func=cmd_status)

    p = sub.add_parser("rcon", help="send raw RCON commands")
    p.add_argument("commands", nargs="+")
    p.set_defaults(func=cmd_rcon)

    p = sub.add_parser("bmh", help="run a bmh harness subcommand, print its JSON")
    p.add_argument("args", nargs="+")
    p.set_defaults(func=cmd_bmh)

    p = sub.add_parser("snapshot", help="copy the level folder to <workspace>/worlds/<name>")
    p.add_argument("name")
    p.set_defaults(func=cmd_snapshot)
    p = sub.add_parser("restore", help="replace the level folder with a snapshot")
    p.add_argument("name")
    p.set_defaults(func=cmd_restore)
    sub.add_parser("delete-level", help="delete the level folder").set_defaults(func=cmd_delete_level)
    sub.add_parser("snapshots").set_defaults(func=cmd_snapshots)

    p = sub.add_parser("scene", help="build a deterministic scene world")
    p.add_argument("name")
    p.set_defaults(func=cmd_scene)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except ServerError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
