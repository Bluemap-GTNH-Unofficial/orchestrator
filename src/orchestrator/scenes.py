"""Deterministic scene worlds built through the `bmh` harness mod.

Every scene starts from an empty level folder, so rerunning a scene rebuilds the same world.
Outputs land in ``<workspace>/out/scenes/<scene>/`` (harness files: manifests, dumps,
registry) and a snapshot of the finished world in ``<workspace>/worlds/<scene>/``.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from orchestrator.server import Server, ServerError

OVERWORLD = 0
ZOO_Y = 5  # superflat surface is y=3; the zoo floor goes at y=4
SETTLE_SECONDS = 15


# bedrock, 2 dirt, grass (surface y=3), plains, no structures; the default preset adds villages
FLAT_NO_STRUCTURES = "2;7,2x3,2;1;"


@dataclass(frozen=True)
class Scene:
    level_type: str
    build: Callable[[Server], dict]
    seed: str = "1710"
    generator_settings: str = ""


def _zoo(server: Server, modid: str) -> dict:
    zoo = server.bmh("zoo", OVERWORLD, 0, ZOO_Y, 0, modid, "zoo.json")
    manifest = json.loads((server.root / "bmh-out" / "zoo.json").read_text(encoding="utf-8"))
    xs = [e["x"] for e in manifest["placed"]]
    zs = [e["z"] for e in manifest["placed"]]
    # one block of margin around the grid, from the floor up to a few blocks above
    box = [min(xs) - 1, ZOO_Y - 1, min(zs) - 1, max(xs) + 1, ZOO_Y + 3, max(zs) + 1]
    return {"zoo": zoo, "dump_box": box}


def _terrain(server: Server) -> dict:
    return {"pregen": server.bmh("pregen", OVERWORLD, -16, -16, 15, 15)}


SCENES: dict[str, Scene] = {
    "vanilla-zoo": Scene(level_type="FLAT", generator_settings=FLAT_NO_STRUCTURES, build=lambda s: _zoo(s, "minecraft")),
    "gtnh-zoo": Scene(level_type="FLAT", generator_settings=FLAT_NO_STRUCTURES, build=lambda s: _zoo(s, "all")),
    "terrain-rwg": Scene(level_type="rwg", build=_terrain),
}


def run(name: str, base: Server, out: Path, snapshot: Path) -> dict:
    scene = SCENES.get(name)
    if scene is None:
        raise ServerError(f"unknown scene {name!r}; known: {', '.join(SCENES)}")
    level = f"scene-{name}"
    config = dataclasses.replace(
        base.config,
        level_name=level,
        level_type=scene.level_type,
        level_seed=scene.seed,
        extra_properties={**base.config.extra_properties, "generator-settings": scene.generator_settings},
    )
    server = Server(config)
    if server.pid() is not None:
        raise ServerError("stop the server before building a scene")

    level_dir = server.root / level
    harness_out = server.root / "bmh-out"
    for path in (level_dir, harness_out):
        if path.exists():
            shutil.rmtree(path)

    started = time.time()
    server.start()
    try:
        result = {"scene": name, "level": level, "ping": server.bmh("ping")}
        for rule in ("doDaylightCycle", "doMobSpawning", "doFireTick", "mobGriefing"):
            server.rcon(f"gamerule {rule} false")
        result["registry"] = server.bmh("registry", "registry.json")
        result.update(scene.build(server))
        # let scheduled block updates settle and delayed tile-entity crashes surface before saving
        time.sleep(SETTLE_SECONDS)
        result["flush"] = server.bmh("flush")
        if "dump_box" in result:
            # dump the settled world right after saving it, so the dump matches what is on disk
            result["dump"] = server.bmh("dump", OVERWORLD, *result["dump_box"], "dump.ndjson")
    except Exception as e:
        crash = server.latest_crash_report(started)
        if crash is not None:
            raise ServerError(f"scene {name} crashed the server: {crash}") from e
        raise
    finally:
        server.stop()
    crash = server.latest_crash_report(started)
    if crash is not None:
        raise ServerError(f"scene {name} produced a crash report: {crash}")

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(harness_out, out)
    if snapshot.exists():
        shutil.rmtree(snapshot)
    shutil.copytree(level_dir, snapshot)
    result["out"] = str(out)
    result["snapshot"] = str(snapshot)
    (out / "scene.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
