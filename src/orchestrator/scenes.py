"""Deterministic scene worlds built through the `bmh` harness mod.

Every scene starts from an empty level folder, so rerunning a scene rebuilds the same world.
Outputs land in ``<workspace>/out/scenes/<scene>/`` (harness files: manifests, dumps,
registry) and a snapshot of the finished world in ``<workspace>/worlds/<scene>/``.
"""

from __future__ import annotations

import dataclasses
import json
import math
import shutil
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from orchestrator.mod_scenes import mod_renderers
from orchestrator.server import Server, ServerError

OVERWORLD = 0
ZOO_Y = 5  # superflat surface is y=3; the zoo floor goes at y=4
SETTLE_SECONDS = 15

# bedrock, 2 dirt, grass (surface y=3), plains, no structures; the default preset adds villages
FLAT_NO_STRUCTURES = "2;7,2x3,2;1;"

# `bmh mtes` types placed as single blocks by gt-machines (multiblock controllers and pipes have their own scenes)
SINGLE_BLOCK_TYPES = frozenset(
    {"machine", "hatch", "generator", "boiler", "tank", "chest", "battery_buffer", "transformer", "hull", "other"}
)
PIPE_TYPES = ("cable", "fluid_pipe", "item_pipe", "pipe", "frame")
CONNECTING_PIPE_TYPES = ("cable", "fluid_pipe", "item_pipe", "pipe")
SPECIAL_PIPE_COLOR = 0  # junctions of `pipe`-type MTEs are painted: TecTech data/laser pipes only connect when painted
SAMPLE_FACINGS = ("SOUTH", "EAST", "WEST")


@dataclass(frozen=True)
class Multiblock:
    """A gt-multiblocks controller: built with ``bmh multiblock <tier> <mode>``, then ``hatches`` placed manually
    (``(dx, dy, dz, mID, facing)`` relative to the controller) where the build leaves them out, then checked."""

    mte: int
    tier: int = 1
    mode: str = "survival"
    hatches: tuple[tuple[int, int, int, int, str], ...] = ()


OUTPUT_BUS_ULV = 80

# one controller every 48 blocks along +x, facing NORTH (the structure extends towards +z)
MULTIBLOCKS: tuple[Multiblock, ...] = (
    Multiblock(1000),  # GT electric blast furnace
    Multiblock(1002),  # GT vacuum freezer
    Multiblock(1001),  # GT implosion compressor
    Multiblock(1169),  # GT large chemical reactor
    Multiblock(1126),  # GT distillation tower
    # GT assembly line: survival builds 9 slices but cannot place the last slice's output bus (its LAST piece overlaps
    # a casing of the previous slice), so the bus goes into the bottom of the 9th slice by hand
    Multiblock(1170, tier=5, hatches=((-8, -2, 0, OUTPUT_BUS_ULV, "DOWN"),)),
    Multiblock(1160),  # GT oil cracking unit
    # GT bricked blast furnace (not an MTEMultiBlockBase, no hatches); survival fills its inside with lava
    Multiblock(140, mode="creative"),
    Multiblock(15524),  # GT large steam turbine
    Multiblock(15543),  # GT++ industrial coke oven
    Multiblock(15542),  # GT++ industrial sifter
    Multiblock(31150),  # GT++ mega alloy blast smelter
    Multiblock(12730),  # bartworks mega blast furnace
    Multiblock(15563),  # bartworks electric implosion compressor
    Multiblock(15331),  # TecTech research station
    Multiblock(15350),  # TecTech energy infuser
    Multiblock(15300),  # TecTech active transformer
    Multiblock(13106),  # kekztech lapotronic supercapacitor
    Multiblock(13104, tier=3),  # kekztech TFFT (tier 1 glass is too low for the energy hatch GT picks)
)
MULTIBLOCK_Y = 20  # well above the superflat ground: survival placement only fills air
MULTIBLOCK_SPACING = 48
MULTIBLOCK_REACH = 24  # dump margin around each controller

TERRAIN_CHUNKS = (-16, -16, 15, 15)  # inclusive chunk rectangle, 1024 chunks
TERRAIN_STRIP = 8  # chunk columns per pregen command
TERRAIN_DUMP_BOX = (0, 0, 0, 31, 255, 31)


@dataclass(frozen=True)
class Scene:
    level_type: str
    build: Callable[[Server], dict]
    description: str
    seed: str = "1710"
    generator_settings: str = ""


def _read_out(server: Server, file: str) -> dict:
    return json.loads((server.root / "bmh-out" / file).read_text(encoding="utf-8"))


def _write_in(server: Server, file: str, data: object) -> None:
    path = server.root / "bmh-out" / file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def union_box(boxes: Iterable[Iterable[int]]) -> list[int]:
    boxes = [list(b) for b in boxes]
    return [min(b[i] for b in boxes) for i in range(3)] + [max(b[i] for b in boxes) for i in range(3, 6)]


CONTEXT_CHUNKS = 2  # chunks generated and populated around every scene's dump box
PREGEN_CAP = 4096  # chunks per `bmh pregen`


def chunk_strips(cx1: int, cz1: int, cx2: int, cz2: int, cap: int = PREGEN_CAP) -> list[tuple[int, int, int, int]]:
    """Splits an inclusive chunk rectangle into strips of whole z-columns, each at most ``cap`` chunks."""
    rows = cz2 - cz1 + 1
    if rows > cap:
        raise ServerError(f"chunk rectangle with {rows} rows does not fit {cap}-chunk strips")
    width = cap // rows
    return [(x, cz1, min(x + width - 1, cx2), cz2) for x in range(cx1, cx2 + 1, width)]


def _zoo(server: Server, modid: str) -> dict:
    zoo = server.bmh("zoo", OVERWORLD, 0, ZOO_Y, 0, modid, "zoo.json")
    manifest = _read_out(server, "zoo.json")
    xs = [e["x"] for e in manifest["placed"]]
    zs = [e["z"] for e in manifest["placed"]]
    # one block of margin around the grid, from the floor up to a few blocks above
    box = [min(xs) - 1, ZOO_Y - 1, min(zs) - 1, max(xs) + 1, ZOO_Y + 3, max(zs) + 1]
    return {"zoo": zoo, "dump_box": box}


def _place_list(server: Server, name: str, entries: list[dict], x: int, z: int) -> dict:
    """`bmh place-list` of ``entries`` from ``<name>.json``; manifest in ``<name>-placed.json``."""
    _write_in(server, f"{name}.json", entries)
    return server.bmh("place-list", OVERWORLD, x, ZOO_Y, z, f"{name}.json", f"{name}-placed.json")


def _mtes(server: Server) -> list[dict]:
    server.bmh("mtes", "mtes.json")
    return _read_out(server, "mtes.json")["mtes"]


NORTH = 2  # ForgeDirection ordinal


def north_list(mtes: list[dict]) -> list[dict]:
    """Every single-block MTE, facing NORTH, or UP/DOWN for machines that only face vertically (e.g. crop managers)."""
    return [{"mte": e["id"], "facing": ["NORTH", "UP", "DOWN"]} for e in mtes if e["type"] in SINGLE_BLOCK_TYPES]


def sample_list(mtes: list[dict], north_placed: list[dict], facing: str) -> list[dict]:
    """The first MTE of each class that was placed facing NORTH, facing ``facing``."""
    by_id = {e["id"]: e for e in mtes}
    sample: dict[str, int] = {}
    for p in north_placed:
        if p["facing"] == NORTH:
            sample.setdefault(by_id[p["mte"]]["class"], p["mte"])
    return [{"mte": mid, "facing": facing} for mid in sample.values()]


def _gt_machines(server: Server) -> dict:
    mtes = _mtes(server)
    results = {"north": _place_list(server, "machines-north", north_list(mtes), 0, 0)}
    north_placed = _read_out(server, "machines-north-placed.json")["placed"]
    x, z = 0, results["north"]["box"][5] + 4
    for facing in SAMPLE_FACINGS:
        key = facing.lower()
        results[key] = _place_list(server, f"machines-{key}", sample_list(mtes, north_placed, facing), x, z)
        x = results[key]["box"][3] + 4
    return {
        "place_lists": results,
        "placed": sum(r["placed"] for r in results.values()),
        "failed": sum(r["failed"] for r in results.values()),
        "dump_box": union_box(r["box"] for r in results.values()),
    }


def ore_list(ores: list[dict]) -> list[dict]:
    """Every material on every `gt.blockores2` stone (normal + small); one material per stone of the other ore blocks."""
    entries = [{"name": e["name"], "meta": e["meta"]} for e in ores if e["name"] == "gregtech:gt.blockores2"]
    seen: set[tuple[str, str, bool]] = set()
    for e in ores:
        key = (e["name"], e["stone"], e["small"])
        if e["name"] != "gregtech:gt.blockores2" and key not in seen:
            seen.add(key)
            entries.append({"name": e["name"], "meta": e["meta"]})
    return entries


def _gt_ores(server: Server) -> dict:
    server.bmh("gt-ores", "gt-ores.json")
    reply = _place_list(server, "ores", ore_list(_read_out(server, "gt-ores.json")["ores"]), 0, 0)
    return {"place_list": reply, "placed": reply["placed"], "failed": reply["failed"], "dump_box": reply["box"]}


@dataclass(frozen=True)
class PipeLine:
    section: str
    mte: int
    start: tuple[int, int, int]
    end: tuple[int, int, int]
    color: int = -1

    def blocks(self) -> list[tuple[int, int, int]]:
        steps = max(abs(e - s) for s, e in zip(self.start, self.end, strict=True))
        delta = [(e > s) - (e < s) for s, e in zip(self.start, self.end, strict=True)]
        return [tuple(s + d * i for s, d in zip(self.start, delta, strict=True)) for i in range(steps + 1)]


def pipe_plan(mtes: list[dict], y: int = ZOO_Y) -> list[PipeLine]:
    """gt-pipes layout, all at x, z >= 0.

    - ``line``: every pipe/cable/frame MTE as a straight 3-block line along x (cells 4 x 2 blocks).
    - ``junction``: per cable/fluid/item pipe type and distinct (thickness, insulated, pipeAmount), and for every other
      pipe MTE (painted), the first MTE as a T, a cross, an L corner and a vertical line (cells 6 x 14 blocks).
    - ``color``: a column of lines with colour -1..15 for the first cable, fluid pipe and item pipe and for every other
      pipe MTE (type ``pipe``; TecTech data/laser pipes only connect when painted, to equal colours).
    Distinct groups never touch; a junction's lines share exactly their junction block.
    """
    pipes = [e for e in mtes if e["type"] in PIPE_TYPES]
    plan: list[PipeLine] = []

    cols = max(1, math.ceil(math.sqrt(len(pipes) / 2)))
    for i, e in enumerate(pipes):
        x, z = 4 * (i % cols), 2 * (i // cols)
        plan.append(PipeLine("line", e["id"], (x, y, z), (x + 2, y, z)))
    z0 = 2 * ((len(pipes) + cols - 1) // cols) + 2

    reps: dict[tuple, dict] = {}
    for e in mtes:
        if e["type"] == "pipe":
            reps.setdefault(("pipe", e["id"]), e)
        elif e["type"] in CONNECTING_PIPE_TYPES:
            reps.setdefault((e["type"], e.get("thickness"), e.get("insulated"), e.get("pipeAmount")), e)
    per_row = max(1, cols * 4 // 6)
    for i, e in enumerate(reps.values()):
        x, z = 6 * (i % per_row), z0 + 14 * (i // per_row)
        m = e["id"]
        c = SPECIAL_PIPE_COLOR if e["type"] == "pipe" else -1
        plan += [
            PipeLine("junction", m, (x, y, z), (x + 4, y, z), c),  # T: bar ...
            PipeLine("junction", m, (x + 2, y, z), (x + 2, y, z + 2), c),  # ... and stem
            PipeLine("junction", m, (x, y, z + 6), (x + 4, y, z + 6), c),  # cross
            PipeLine("junction", m, (x + 2, y, z + 4), (x + 2, y, z + 8), c),
            PipeLine("junction", m, (x, y, z + 10), (x + 2, y, z + 10), c),  # L corner
            PipeLine("junction", m, (x + 2, y, z + 10), (x + 2, y, z + 12), c),
            PipeLine("junction", m, (x + 4, y, z + 10), (x + 4, y + 2, z + 10), c),  # vertical
        ]
    z0 += 14 * ((len(reps) + per_row - 1) // per_row)

    coloured: dict[object, dict] = {}
    for e in mtes:
        if e["type"] in CONNECTING_PIPE_TYPES:
            coloured.setdefault(e["id"] if e["type"] == "pipe" else e["type"], e)
    for t, e in enumerate(coloured.values()):
        for c, color in enumerate(range(-1, 16)):
            x, z = 4 * t, z0 + 2 * c
            plan.append(PipeLine("color", e["id"], (x, y, z), (x + 2, y, z), color))
    return plan


def _gt_pipes(server: Server) -> dict:
    plan = pipe_plan(_mtes(server))
    blocks = [b for line in plan for b in line.blocks()]
    box = union_box([[*b, *b] for b in blocks])
    box = [box[0] - 1, ZOO_Y - 1, box[2] - 1, box[3] + 1, box[4] + 1, box[5] + 1]
    # populate first (as the zoo does) so world decoration cannot overwrite the pipes, then lay a stone floor
    server.bmh("pregen", OVERWORLD, (box[0] >> 4) - 1, (box[2] >> 4) - 1, box[3] >> 4, box[5] >> 4)
    server.bmh("fill", OVERWORLD, box[0], ZOO_Y - 1, box[2], box[3], ZOO_Y - 1, box[5], "minecraft:stone", 0)
    placed, failed, counts = [], [], {}
    for line in plan:
        try:
            reply = server.bmh("pipe", OVERWORLD, *line.start, *line.end, line.mte, line.color)
        except ServerError as e:
            failed.append({"section": line.section, "mte": line.mte, "start": line.start, "reason": str(e)})
            continue
        placed.append({"section": line.section, "mte": line.mte, "start": line.start, "end": line.end,
                       "color": line.color, **reply})  # fmt: skip
        counts[line.section] = counts.get(line.section, 0) + 1
    (server.root / "bmh-out" / "pipes.json").write_text(
        json.dumps({"placed": placed, "failed": failed}), encoding="utf-8"
    )
    return {"lines": counts, "placed": len(placed), "failed": len(failed), "dump_box": box}


def _gt_multiblocks(server: Server) -> dict:
    n = len(MULTIBLOCKS)
    x_max = MULTIBLOCK_SPACING * (n - 1)
    r = MULTIBLOCK_REACH
    box = [-r, ZOO_Y - 1, -r, x_max + r, MULTIBLOCK_Y + 2 * r, 2 * r]
    server.bmh("pregen", OVERWORLD, (box[0] >> 4) - 1, (box[2] >> 4) - 1, box[3] >> 4, box[5] >> 4)
    results = []
    for i, spec in enumerate(MULTIBLOCKS):
        x, y, z = MULTIBLOCK_SPACING * i, MULTIBLOCK_Y, 0
        entry: dict = {"mte": spec.mte, "tier": spec.tier, "x": x, "y": y, "z": z}
        try:
            entry["name"] = server.bmh("mte", OVERWORLD, x, y, z, spec.mte, "NORTH")["name"]
            entry["build"] = server.bmh("multiblock", OVERWORLD, x, y, z, spec.tier, spec.mode)
            if spec.hatches and entry["build"]["formed"] is False:
                entry["hatches"] = [
                    server.bmh("mte", OVERWORLD, x + dx, y + dy, z + dz, mid, facing)["name"]
                    for dx, dy, dz, mid, facing in spec.hatches
                ]
                entry["check"] = server.bmh("multiblock", OVERWORLD, x, y, z, spec.tier, "check")
        except ServerError as e:
            entry["error"] = str(e)
        entry["formed"] = entry.get("check", entry.get("build", {})).get("formed")
        results.append(entry)
    (server.root / "bmh-out" / "multiblocks.json").write_text(json.dumps(results), encoding="utf-8")
    return {
        "multiblocks": results,
        "placed": sum("error" not in e for e in results),
        "failed": sum("error" in e for e in results),
        "formed": sum(e["formed"] is True for e in results),
        "not_multiblockbase": sum(e["formed"] is None and "error" not in e for e in results),
        "dump_box": box,
    }


def _terrain(server: Server) -> dict:
    cx1, cz1, cx2, cz2 = TERRAIN_CHUNKS
    strips = []
    for x in range(cx1, cx2 + 1, TERRAIN_STRIP):
        strips.append(server.bmh("pregen", OVERWORLD, x, cz1, min(x + TERRAIN_STRIP - 1, cx2), cz2))
    pregen = {"chunks": sum(s["chunks"] for s in strips), "ms": sum(s["ms"] for s in strips)}
    return {"pregen": pregen, "dump_box": list(TERRAIN_DUMP_BOX)}


def _flat(build: Callable[[Server], dict], description: str) -> Scene:
    return Scene(level_type="FLAT", generator_settings=FLAT_NO_STRUCTURES, build=build, description=description)


SCENES: dict[str, Scene] = {
    "vanilla-zoo": _flat(lambda s: _zoo(s, "minecraft"), "every vanilla block variant (meta 0..15) on a grid"),
    "gtnh-zoo": _flat(lambda s: _zoo(s, "all"), "every registered block variant (meta 0..15) on a grid"),
    "gt-machines": _flat(_gt_machines, "every single-block GT MTE facing NORTH; one per class facing SOUTH/EAST/WEST"),
    "gt-pipes": _flat(_gt_pipes, "every GT pipe/cable/frame as a line; T, cross, L, vertical and colour samples"),
    "gt-ores": _flat(_gt_ores, "every GT ore material on each gt.blockores2 stone, normal + small; other stones sampled"),
    "gt-multiblocks": _flat(_gt_multiblocks, "GT, GT++, bartworks, TecTech, kekztech multiblocks built with hatches"),
    "terrain-rwg": Scene(level_type="rwg", build=_terrain, description="RWG terrain, 32x32 chunks pregenerated"),
    "mod-renderers": _flat(mod_renderers, "Chisel CTM, Iron Chests, BiblioCraft, AE2 cables + parts, EnderIO conduits"),
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
        build_started = time.time()
        result.update(scene.build(server))
        result["build_seconds"] = round(time.time() - build_started, 1)
        if "dump_box" in result:
            x1, _, z1, x2, _, z2 = result["dump_box"]
            # generate and populate the chunks around the scene: BlueMap skips hires tiles touching chunks that are
            # missing or unpopulated, which clipped scene edges in renders
            m = CONTEXT_CHUNKS
            strips = chunk_strips((x1 >> 4) - m, (z1 >> 4) - m, (x2 >> 4) + m, (z2 >> 4) + m)
            pregens = [server.bmh("pregen", OVERWORLD, *s) for s in strips]
            result["context_pregen"] = {"chunks": sum(p["chunks"] for p in pregens), "ms": sum(p["ms"] for p in pregens)}
            # keep the dumped chunks plus a one-chunk margin loaded: their tile entities tick and settle, liquids from
            # outside cannot flow in later, and the dump after the flush reads exactly what was saved
            chunks = ((x1 >> 4) - 1, (z1 >> 4) - 1, (x2 >> 4) + 1, (z2 >> 4) + 1)
            result["hold"] = server.bmh("hold", OVERWORLD, *chunks)
        # let scheduled block updates settle and delayed tile-entity crashes surface before saving
        time.sleep(SETTLE_SECONDS)
        if "dump_box" in result:
            # stop what is still moving (e.g. lava flowing in generated caves), so flush, dump and the final save agree
            result["drop_ticks"] = server.bmh("drop-ticks", OVERWORLD, *chunks)
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
    result["seconds"] = round(time.time() - started, 1)
    (out / "scene.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
