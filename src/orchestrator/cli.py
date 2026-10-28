"""`orch` command line: server lifecycle, RCON, bmh harness, world snapshots, scenes."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
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


def verify_dump(result: dict) -> dict:
    """Runs `:legacy:verifyDump` on a scene's snapshot and dump (box = the dump box)."""
    args = [result["snapshot"], "minecraft:overworld", str(Path(result["out"]) / "dump.ndjson"), "--box"]
    args += [str(v) for v in result["dump_box"]]
    cmd = ["mise", "exec", "--", "./gradlew", "-q", ":legacy:verifyDump", "--args=" + " ".join(args)]
    started = time.time()
    proc = subprocess.run(cmd, cwd=workspace() / "BlueMap-GTNH", capture_output=True, text=True)
    match = re.search(r"^mismatches: (\d+)$", proc.stdout, re.MULTILINE)
    report = proc.stdout.strip().splitlines()[:60]
    if match is None:
        report += proc.stderr.strip().splitlines()[-30:]
    return {
        "mismatches": int(match.group(1)) if match else None,
        "exit": proc.returncode,
        "seconds": round(time.time() - started, 1),
        "report": report,
    }


def scene_out(name: str) -> Path:
    return workspace() / "out" / "scenes" / name


def verify_scene(name: str) -> dict:
    """verifyDump for an already built scene; stores the result in its scene.json."""
    path = scene_out(name) / "scene.json"
    if not path.is_file():
        raise ServerError(f"{path} does not exist; build the scene first")
    result = json.loads(path.read_text(encoding="utf-8"))
    if "dump_box" not in result:
        raise ServerError(f"scene {name} has no dump")
    result["verify"] = verify_dump(result)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def run_scene(args: argparse.Namespace, name: str) -> dict:
    from orchestrator import scenes

    result = scenes.run(name, make_server(args), scene_out(name), snapshots_dir() / name)
    if args.verify and "dump_box" in result:
        result = verify_scene(name)
    return result


def cmd_verify(args: argparse.Namespace) -> None:
    verify = verify_scene(args.name)["verify"]
    print(json.dumps(verify, indent=2))
    if verify["mismatches"] != 0:
        raise ServerError(f"verifyDump of {args.name}: {verify['mismatches']} mismatches (exit {verify['exit']})")


def cmd_scene(args: argparse.Namespace) -> None:
    from orchestrator import scenes

    if args.list:
        for name, scene in scenes.SCENES.items():
            servers = ",".join(sorted(scene.servers))
            print(f"{name:18} {scene.level_type:5} {servers:16} {scene.description}")
        return
    if args.name is None:
        raise ServerError("scene name required (or --list, or all)")
    if args.name != "all":
        print(json.dumps(run_scene(args, args.name), indent=2))
        return
    runnable, skipped = scenes.plan(args.server)
    for name, reason in skipped.items():
        print(json.dumps({name: {"skipped": reason}}), flush=True)
    summary: dict[str, dict] = {}
    for name in runnable:
        try:
            result = run_scene(args, name)
        except ServerError as e:
            summary[name] = {"error": str(e)}
        else:
            summary[name] = {
                k: result[k] for k in ("placed", "failed", "formed", "pregen", "dump", "verify", "seconds") if k in result
            }
        print(json.dumps({name: summary[name]}), flush=True)
    print(json.dumps(summary, indent=2))
    failed = [n for n, s in summary.items() if "error" in s or s.get("verify", {}).get("mismatches", 0) != 0]
    if failed:
        raise ServerError(f"scenes failed: {', '.join(failed)}")


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
    p.add_argument("args", nargs=argparse.REMAINDER, help="subcommand and arguments (options such as --tag pass through)")
    p.set_defaults(func=cmd_bmh)

    p = sub.add_parser("snapshot", help="copy the level folder to <workspace>/worlds/<name>")
    p.add_argument("name")
    p.set_defaults(func=cmd_snapshot)
    p = sub.add_parser("restore", help="replace the level folder with a snapshot")
    p.add_argument("name")
    p.set_defaults(func=cmd_restore)
    sub.add_parser("delete-level", help="delete the level folder").set_defaults(func=cmd_delete_level)
    sub.add_parser("snapshots").set_defaults(func=cmd_snapshots)

    p = sub.add_parser("scene", help="build a deterministic scene world (or `all` of them)")
    p.add_argument("name", nargs="?", help="scene name or `all`")
    p.add_argument("--list", action="store_true", help="list scenes")
    p.add_argument("--verify", action="store_true", help="run :legacy:verifyDump on each scene's dump")
    p.set_defaults(func=cmd_scene)
    p = sub.add_parser("verify", help="run :legacy:verifyDump on a built scene (out/scenes/<name>, worlds/<name>)")
    p.add_argument("name")
    p.set_defaults(func=cmd_verify)
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
