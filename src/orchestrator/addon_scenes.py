"""Scenes for the community GTNH addons (run on a server that has them, e.g. ``--server gtnh-addons``).

- ``addons-zoo``: a ``bmh zoo`` grid per addon block namespace, side by side along +x.
- ``addons-machines``: every addon MetaTileEntity (picked by class package from ``bmh mtes``), one ``place-list`` per
  addon along +x, facing NORTH (UP/DOWN when NORTH is refused).
- ``addons-multiblocks``: flagship multiblocks of each addon built with ``bmh multiblock`` around controllers at
  y=20, z=0 (facing NORTH, structures extend towards +z), a row of the addons' TESR blocks with default tile entities
  on a floor at z=-48, and a row of TESR blocks with their effects switched on through ``bmh te-nbt`` at z=-64.

Addon versions: <workspace>/downloads/addons/versions.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from orchestrator.server import Server, ServerError

OVERWORLD = 0
Y = 5  # superflat surface is y=3; grids put their stone floor at y=4
GAP = 6  # blocks between neighbouring grids


@dataclass(frozen=True)
class Addon:
    key: str
    namespace: str  # block registry namespace (the zoo's modid filter)
    packages: tuple[str, ...]  # MetaTileEntity class packages


ADDONS: tuple[Addon, ...] = (
    Addon("tst", "TwistSpaceTechnology", ("com.Nxer.TwistSpaceTechnology.",)),
    Addon("gtnl", "sciencenotleisure", ("com.science.gtnl.",)),
    Addon("ph", "programmablehatches", ("reobf.proghatches.",)),
    Addon("123t", "123Technology", ("com.newmaa.othtech.",)),
    Addon("nhu", "NHUtilities", ("com.xir.NHUtilities.",)),
    Addon("boxpp", "boxplusplus", ("com.silvermoon.boxplusplus.",)),
)


def _read_out(server: Server, file: str) -> dict:
    return json.loads((server.root / "bmh-out" / file).read_text(encoding="utf-8"))


def _write_in(server: Server, file: str, data: object) -> None:
    path = server.root / "bmh-out" / file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _union(boxes: list[list[int]]) -> list[int]:
    return [min(b[i] for b in boxes) for i in range(3)] + [max(b[i] for b in boxes) for i in range(3, 6)]


def _require_addons(server: Server) -> None:
    """The scenes need every addon; `scenes.run` writes registry.json before building."""
    namespaces = {b["name"].partition(":")[0] for b in _read_out(server, "registry.json")["blocks"]}
    missing = [a.namespace for a in ADDONS if a.namespace not in namespaces]
    if missing:
        raise ServerError(f"addons missing on this server: {', '.join(missing)} (use --server gtnh-addons)")


def _addons_zoo(server: Server) -> dict:
    _require_addons(server)
    x = 0
    zoos: dict[str, dict] = {}
    boxes = []
    for addon in ADDONS:
        file = f"zoo-{addon.key}.json"
        reply = server.bmh("zoo", OVERWORLD, x, Y, 0, addon.namespace, file)
        placed = _read_out(server, file)["placed"]
        xs = [e["x"] for e in placed]
        zs = [e["z"] for e in placed]
        box = [min(xs) - 1, Y - 1, min(zs) - 1, max(xs) + 1, Y + 3, max(zs) + 1]
        zoos[addon.key] = {**reply, "box": box}
        boxes.append(box)
        x = max(xs) + GAP
    return {
        "zoos": zoos,
        "placed": sum(z["placed"] for z in zoos.values()),
        "failed": sum(z["failed"] for z in zoos.values()),
        "dump_box": _union(boxes),
    }


# MTEs that crash the RC-2 server when they tick (addon built against another GT); left out of addons-machines
CRASHING_MTES: dict[int, str] = {
    21153: "GTNL ETGWEyeOfHarmonyModule: NoSuchMethodError getActivitySoundLoop() returning SoundResource",
}


def addon_mtes(mtes: list[dict], addon: Addon) -> list[dict]:
    return [e for e in mtes if e["class"].startswith(addon.packages) and e["id"] not in CRASHING_MTES]


def _addons_machines(server: Server) -> dict:
    _require_addons(server)
    server.bmh("mtes", "mtes.json")
    mtes = _read_out(server, "mtes.json")["mtes"]
    x = 0
    lists: dict[str, dict] = {}
    for addon in ADDONS:
        entries = [{"mte": e["id"], "facing": ["NORTH", "UP", "DOWN"]} for e in addon_mtes(mtes, addon)]
        name = f"machines-{addon.key}"
        _write_in(server, f"{name}.json", entries)
        reply = server.bmh("place-list", OVERWORLD, x, Y, 0, f"{name}.json", f"{name}-placed.json")
        lists[addon.key] = {**reply, "mtes": len(entries)}
        x = reply["box"][3] + GAP
    return {
        "place_lists": lists,
        "placed": sum(r["placed"] for r in lists.values()),
        "failed": sum(r["failed"] for r in lists.values()),
        "excluded": {str(k): v for k, v in CRASHING_MTES.items()},
        "dump_box": _union([r["box"] for r in lists.values()]),
    }


@dataclass(frozen=True)
class AddonMultiblock:
    """A controller built with ``bmh multiblock <tier> <mode>``; ``west``/``east`` = how far the built structure reaches
    towards -x/+x of the controller (measured), which sets the spacing."""

    mte: int
    west: int
    east: int
    mode: str = "survival"
    tier: int = 1


MULTIBLOCKS: tuple[AddonMultiblock, ...] = (
    AddonMultiblock(19015, 18, 18),  # TST artificial star
    AddonMultiblock(19072, 9, 9),  # TST laser meteor miner (laser beacon)
    AddonMultiblock(19076, 6, 6),  # TST large solar boiler
    AddonMultiblock(19034, 16, 16),  # TST eye of wood
    AddonMultiblock(19001, 5, 5),  # TST intensify chemical distorter
    AddonMultiblock(19006, 9, 9),  # TST magnetic mixer
    AddonMultiblock(19003, 10, 10),  # TST miracle top
    AddonMultiblock(21027, 11, 11),  # GTNL mega blast furnace
    AddonMultiblock(21022, 1, 5),  # GTNL large circuit assembler
    AddonMultiblock(21014, 3, 3),  # GTNL large steam furnace
    AddonMultiblock(21020, 9, 9),  # GTNL meteor miner (laser beacon)
    AddonMultiblock(21102, 1, 1),  # GTNL large bronze boiler
    AddonMultiblock(21129, 10, 10),  # GTNL nano phagocytosis plant
    AddonMultiblock(23533, 21, 26),  # 123T SINOPEC
    AddonMultiblock(23582, 26, 10),  # 123T fire rocket assembler
    AddonMultiblock(23526, 17, 17),  # 123T mega QFT
    AddonMultiblock(23521, 31, 32),  # 123T mega Isa forge
    AddonMultiblock(25000, 1, 1),  # NHU arcane industrial EBF
    AddonMultiblock(22116, 1, 1),  # PH large programming circuit provider
    AddonMultiblock(17001, 11, 11, mode="creative"),  # Box++ production line encapsulator (survival leaves it unformed)
)
MULTIBLOCK_Y = 20  # well above the superflat ground: survival placement only fills air
MULTIBLOCK_GAP = 8
MULTIBLOCK_BOX_Y = (Y - 1, MULTIBLOCK_Y + 52)  # tallest: mega Isa forge, 46 above its controller
MULTIBLOCK_BOX_Z = (-24, 48)  # structures reach z -19..+44 (123T's epic coke oven, > 97x11x97, is left out)

# blocks with a TileEntitySpecialRenderer, one per cell along +x at z=TESR_Z
TESR_BLOCKS: tuple[str, ...] = (
    "TwistSpaceTechnology:tst.star",
    "TwistSpaceTechnology:tile.LaserBeacon",
    "TwistSpaceTechnology:tst.eyeofwoodrender",
    "TwistSpaceTechnology:tst.largesolarboilerrender",
    "TwistSpaceTechnology:BlockArcaneHole",
    "TwistSpaceTechnology:BlockPowerChair",
    "sciencenotleisure:beam_former",
    "sciencenotleisure:laser_beacon",
    "sciencenotleisure:multi_essentia_jar",
    "sciencenotleisure:multi_essentia_tube",
    "sciencenotleisure:artificial_star_render",
    "sciencenotleisure:eternal_greg_tech_workshop_render",
    "sciencenotleisure:nano_phagocytosis_plant_render",
    "sciencenotleisure:player_doll",
    "sciencenotleisure:pigmee_fumo",
    "sciencenotleisure:water_candle",
    "sciencenotleisure:ender_elevator_block",
    "boxplusplus:tile.boxplusplus_BoxRing1",
    "boxplusplus:tile.boxplusplus_BoxRing2",
    "boxplusplus:tile.boxplusplus_BoxRing3",
    "123Technology:tile.rockerrender",
    "123Technology:modelAyanami",
    "123Technology:modelAsuka",
    "123Technology:modelTallHat",
)
TESR_Z = -48
TESR_SPACING = 8


@dataclass(frozen=True)
class ActiveTesr:
    """A TESR block at (x, ACTIVE_TESR_Z + dz) with tile entity NBT (SNBT, merged by `bmh te-nbt`) that switches its
    effect on (beams, rings, star, stored aspects) or picks a non-default variant."""

    name: str
    x: int
    meta: int = 0
    dz: int = 0
    snbt: str = ""


ACTIVE_TESR_Z = -64
ACTIVE_TESRS: tuple[ActiveTesr, ...] = (
    ActiveTesr("TwistSpaceTechnology:tile.LaserBeacon", 0, snbt="{shouldRender:1b,range:20d,rgb_red:1f}"),
    ActiveTesr("sciencenotleisure:laser_beacon", 12, snbt="{shouldRender:1b,range:12d,rgb_blue:1f}"),
    # TileStar writes its size as "renderStatus" but reads it from "size"
    ActiveTesr("TwistSpaceTechnology:tst.star", 24, snbt="{size:1d}"),
    ActiveTesr(
        "sciencenotleisure:multi_essentia_jar",
        36,
        snbt='{StoredAspects:{Aspects:[{key:"ignis",amount:1000},{key:"aqua",amount:500}]},ActiveAspect:"ignis"}',
    ),
    # two beam formers 6 blocks apart facing each other
    ActiveTesr("sciencenotleisure:beam_former", 48, snbt='{orientation_forward:"SOUTH",orientation_up:"UP"}'),
    ActiveTesr("sciencenotleisure:beam_former", 48, dz=6, snbt='{orientation_forward:"NORTH",orientation_up:"UP"}'),
    ActiveTesr("sciencenotleisure:ender_elevator_block", 60, meta=14),
    ActiveTesr("sciencenotleisure:pigmee_fumo", 68, meta=5),
    ActiveTesr("sciencenotleisure:player_doll", 76, meta=3),
    ActiveTesr("boxplusplus:tile.boxplusplus_BoxRing1", 100, snbt="{renderStatus:1b,switch:1b,count:3,scale:0.3f}"),
)


def _place_tesr(server: Server, tag: str, name: str, meta: int, x: int, z: int, snbt: str = "") -> dict:
    """One block as a single-entry place-list (stone floor under it), then its tile entity NBT patched."""
    _write_in(server, f"{tag}.json", [{"name": name, "meta": meta}])
    entry: dict = {"name": name, "meta": meta, "x": x, "z": z}
    try:
        reply = server.bmh("place-list", OVERWORLD, x, Y, z, f"{tag}.json", f"{tag}-placed.json")
        entry["placed"] = reply["placed"]
        if reply["failed"]:
            entry["error"] = json.dumps(_read_out(server, f"{tag}-placed.json").get("failed"))
        elif snbt:
            server.te_nbt(OVERWORLD, x, Y, z, snbt, file=f"{tag}-nbt")
            entry["nbt"] = snbt
    except ServerError as e:
        entry["error"] = str(e)
    return entry


def multiblock_xs() -> list[int]:
    """Controller x positions: neighbouring structures MULTIBLOCK_GAP blocks apart, the first controller at x=0."""
    xs = [0]
    for prev, cur in zip(MULTIBLOCKS, MULTIBLOCKS[1:], strict=False):
        xs.append(xs[-1] + prev.east + MULTIBLOCK_GAP + cur.west)
    return xs


def _addons_multiblocks(server: Server) -> dict:
    _require_addons(server)
    xs = multiblock_xs()
    tesr_x2 = TESR_SPACING * (len(TESR_BLOCKS) - 1)
    x1 = min(-MULTIBLOCKS[0].west, 0) - 2
    x2 = max(xs[-1] + MULTIBLOCKS[-1].east, tesr_x2) + 2
    z1 = min(ACTIVE_TESR_Z - 2, MULTIBLOCK_BOX_Z[0])
    box = [x1, MULTIBLOCK_BOX_Y[0], z1, x2, MULTIBLOCK_BOX_Y[1], MULTIBLOCK_BOX_Z[1]]
    server.bmh("pregen", OVERWORLD, (box[0] >> 4) - 1, (box[2] >> 4) - 1, box[3] >> 4, box[5] >> 4)
    # keep the chunks loaded from now on: a reload re-reads tile entities from disk, and TST's TileStar loses its size
    # there (it writes "renderStatus" but reads "size"), so the patched star must stay loaded until the flush
    server.bmh("hold", OVERWORLD, box[0] >> 4, box[2] >> 4, box[3] >> 4, box[5] >> 4)
    results = []
    for x, spec in zip(xs, MULTIBLOCKS, strict=True):
        y, z = MULTIBLOCK_Y, 0
        entry: dict = {"mte": spec.mte, "mode": spec.mode, "x": x, "y": y, "z": z}
        try:
            entry["name"] = server.bmh("mte", OVERWORLD, x, y, z, spec.mte, "NORTH")["name"]
            entry["build"] = server.bmh("multiblock", OVERWORLD, x, y, z, spec.tier, spec.mode)
        except ServerError as e:
            entry["error"] = str(e)
        entry["formed"] = entry.get("build", {}).get("formed")
        results.append(entry)
    tesrs = [
        _place_tesr(server, f"tesr-{i}", name, 0, TESR_SPACING * i, TESR_Z) for i, name in enumerate(TESR_BLOCKS)
    ]
    tesrs += [
        _place_tesr(server, f"tesr-active-{i}", t.name, t.meta, t.x, ACTIVE_TESR_Z + t.dz, t.snbt)
        for i, t in enumerate(ACTIVE_TESRS)
    ]
    _write_in(server, "multiblocks.json", {"multiblocks": results, "tesrs": tesrs})
    return {
        "multiblocks": results,
        "tesrs": tesrs,
        "placed": sum("error" not in e for e in results + tesrs),
        "failed": sum("error" in e for e in results + tesrs),
        "formed": sum(e["formed"] is True for e in results),
        "dump_box": box,
    }


# name -> (build, description); registered as superflat scenes in scenes.SCENES
ADDON_SCENES = {
    "addons-zoo": (_addons_zoo, "community addons: every block variant of TST, GTNL, PH, 123T, NHU, Box++ on grids"),
    "addons-machines": (_addons_machines, "community addons: every addon MTE (by class package) facing NORTH"),
    "addons-multiblocks": (_addons_multiblocks, "community addons: flagship multiblocks + TESR blocks"),
}
