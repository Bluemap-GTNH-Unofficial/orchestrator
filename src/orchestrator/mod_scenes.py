"""The `mod-renderers` scene: Chisel CTM, Iron Chests, BiblioCraft, AE2 cable buses and EnderIO conduits.

Everything is placed like a player would (`bmh use` right-clicks with the item, `bmh fill` for Chisel blocks), so
tile entities carry the NBT the mods write themselves (facings, AE2 parts, conduit connections).

Layout on the superflat world: a stone floor at y=4, blocks from y=5, one section per mod along +z.
"""

from __future__ import annotations

import json

from orchestrator.server import Server

OVERWORLD = 0
FLOOR_Y = 4
Y = 5

# (registry name, meta, shape): CTMX cubes; V9/V4/R* cubes; CTMV pillars; CTMH rows. Picked from chisel.json.
CHISEL_SAMPLES: list[tuple[str, int, str]] = [
    ("chisel:factoryblock", 0, "cube"),  # CTMX dots
    ("chisel:factoryblock", 4, "cube"),  # CTMX wireframe white
    ("chisel:aluminumblock", 0, "cube"),  # CTMX caution
    ("chisel:aluminumblock", 1, "cube"),  # CTMX crate
    ("chisel:glass", 2, "cube"),  # CTMX glass (if it has a variation)
    ("chisel:factoryblock", 13, "cube"),  # V9 plating
    ("chisel:arcane", 9, "cube"),  # V9 arcane matrix
    ("chisel:stonebricksmooth", 0, "cube"),  # V4 mason bricks
    ("chisel:arcane", 3, "cube"),  # R16 runes
    ("chisel:technical", 12, "cube"),  # R9 bolted plates
    ("chisel:technical4", 0, "cube"),  # R4 panels
    ("chisel:factoryblock", 15, "pillar"),  # CTMV column
    ("chisel:dirt", 10, "pillar"),  # CTMV
    ("chisel:bookshelf", 1, "row"),  # CTMH rainbow
    ("chisel:bookshelf", 4, "row"),  # CTMH red tomes
]
CHISEL_Z = 0

IRON_CHEST_Z = 12
IRON_CHEST_METAS = range(11)  # IRON, GOLD, DIAMOND, COPPER, STEEL, CRYSTAL, OBSIDIAN, DIRT, NETHERITE, DARKSTEEL, SILVER

BIBLIO_Z = 18
# (item, meta, yaw); items whose name has a space go through place-list
BIBLIO_ITEMS: list[tuple[str, int, int]] = [
    *[("BiblioCraft:Bibliotheca", m, (m * 90) % 360) for m in range(7)],
    ("BiblioCraft:BookcaseFilled", 0, 0),
    *[("BiblioCraft:BiblioShelf", m, (m * 90) % 360) for m in range(4)],
    ("BiblioCraft:BiblioPotionShelf", 0, 0),
    ("BiblioCraft:BiblioRack", 0, 90),
    ("BiblioCraft:BiblioCase", 0, 180),
    ("BiblioCraft:BiblioLabel", 0, 0),
    ("BiblioCraft:BiblioLabel", 1, 270),
    ("BiblioCraft:BiblioDesk", 0, 0),
    ("BiblioCraft:BiblioSeats", 0, 90),
    ("BiblioCraft:BiblioTable", 0, 0),
    ("BiblioCraft:BiblioTable", 3, 0),
    ("BiblioCraft:Armor Stand", 0, 0),
    ("BiblioCraft:Armor Stand", 0, 90),
    ("BiblioCraft:BiblioLamp", 0, 0),
    ("BiblioCraft:BiblioLantern", 0, 0),
    ("BiblioCraft:BiblioFancySign", 0, 0),
    ("BiblioCraft:BiblioSwordPedestal", 0, 0),
    ("BiblioCraft:BiblioTypewriter", 0, 0),
    ("BiblioCraft:tile.BiblioFramedChest", 0, 0),
    ("BiblioCraft:BiblioWorkbench", 0, 0),
    ("BiblioCraft:BiblioClock", 0, 0),
    ("BiblioCraft:BiblioMapFrames", 0, 0),
    ("BiblioCraft:BiblioPaneler", 0, 0),
    ("BiblioCraft:BiblioStuffs", 0, 0),
    ("BiblioCraft:Printing Press", 0, 0),
    ("BiblioCraft:Typesetting Machine", 0, 0),
]
# a 2x2 table group (tables merge their tops) and a 3-long shelf row
BIBLIO_GROUP_Z = BIBLIO_Z + 4

AE2_Z = 30
AE2_PART = "appliedenergistics2:item.ItemMultiPart"
# ItemMultiPart damage: cable bases + colour 0..15, 16 = fluix (PartType base meta + AEColor ordinal)
AE2_CABLES = {"glass": 0, "covered": 20, "smart": 40, "dense": 60}
FLUIX = 16
AE2_PARTS = {  # part damage -> side of the cable it is put on
    "terminal": 380,
    "crafting_terminal": 360,
    "pattern_terminal": 340,
    "interface": 440,
    "import_bus": 240,
    "export_bus": 260,
    "storage_bus": 220,
    "level_emitter": 280,
    "annihilation_plane": 300,
    "formation_plane": 320,
    "monitor": 160,
    "storage_monitor": 400,
    "toggle_bus": 80,
    "quartz_fiber": 140,
    "cable_anchor": 120,
}

ENDERIO_Z = 42
CONDUITS = [
    ("EnderIO:itemItemConduit", 0),
    ("EnderIO:itemLiquidConduit", 0),
    ("EnderIO:itemLiquidConduit", 1),
    ("EnderIO:itemLiquidConduit", 2),
    ("EnderIO:itemPowerConduit", 0),
    ("EnderIO:itemPowerConduit", 1),
    ("EnderIO:itemPowerConduit", 2),
    ("EnderIO:itemRedstoneConduit", 0),
    ("EnderIO:itemMEConduit", 0),
]


def _write_in(server: Server, file: str, data: object) -> None:
    path = server.root / "bmh-out" / file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _place_one(server: Server, name: str, entry: dict, x: int, z: int) -> dict:
    """A single place-list entry at x/Y/z (place-list puts entry 0 exactly at its origin)."""
    _write_in(server, f"{name}.json", [entry])
    return server.bmh("place-list", OVERWORLD, x, Y, z, f"{name}.json", f"{name}-placed.json")


def _try(log: list, what: str, fn) -> None:
    try:
        log.append({"what": what, "reply": fn()})
    except Exception as e:  # noqa: BLE001 - one unplaceable sample must not abort the scene
        log.append({"what": what, "error": str(e)})


def _chisel(server: Server, log: list) -> None:
    x = 0
    for name, meta, shape in CHISEL_SAMPLES:
        z = CHISEL_Z
        if shape == "cube":
            _try(log, f"{name}:{meta} cube", lambda: server.bmh("fill", OVERWORLD, x, Y, z, x + 2, Y + 2, z + 2, name, meta))
        elif shape == "pillar":
            # vertical pillar, a horizontal one along x on the ground and one along z next to it
            _try(log, f"{name}:{meta} pillar", lambda: server.bmh("fill", OVERWORLD, x, Y, z, x, Y + 2, z, name, meta))
            _try(log, f"{name}:{meta} beam x", lambda: server.bmh("fill", OVERWORLD, x + 1, Y, z + 2, x + 3, Y, z + 2, name, meta))
            _try(log, f"{name}:{meta} beam z", lambda: server.bmh("fill", OVERWORLD, x + 2, Y, z + 4, x + 2, Y, z + 6, name, meta))
        elif shape == "row":
            _try(log, f"{name}:{meta} row", lambda: server.bmh("fill", OVERWORLD, x, Y, z, x + 2, Y, z, name, meta))
            _try(log, f"{name}:{meta} wall", lambda: server.bmh("fill", OVERWORLD, x, Y, z + 3, x + 2, Y + 1, z + 3, name, meta))
        x += 5


def _iron_chests(server: Server, log: list) -> None:
    # every type, facing rotating through the four yaws; then the iron chest in all four facings
    for i, meta in enumerate(IRON_CHEST_METAS):
        yaw = (i % 4) * 90
        _try(log, f"ironchest {meta} yaw {yaw}", lambda: server.use(OVERWORLD, i * 2, FLOOR_Y, IRON_CHEST_Z, "UP", "IronChest:BlockIronChest", meta, yaw))
    for k, yaw in enumerate((0, 90, 180, 270)):
        _try(log, f"ironchest 0 yaw {yaw}", lambda: server.use(OVERWORLD, k * 2, FLOOR_Y, IRON_CHEST_Z + 2, "UP", "IronChest:BlockIronChest", 0, yaw))
    # vanilla chests (single, double) for comparison
    _try(log, "chest", lambda: server.use(OVERWORLD, 10, FLOOR_Y, IRON_CHEST_Z + 2, "UP", "minecraft:chest", 0, 0))
    for dx in (0, 1):
        _try(log, "double chest", lambda: server.use(OVERWORLD, 12 + dx, FLOOR_Y, IRON_CHEST_Z + 2, "UP", "minecraft:chest", 0, 0))


def _bibliocraft(server: Server, log: list) -> None:
    for i, (item, meta, yaw) in enumerate(BIBLIO_ITEMS):
        x = i * 2
        z = BIBLIO_Z
        if " " in item:
            entry = {"use": {"item": item, "meta": meta, "yaw": yaw}}
            _try(log, f"{item}:{meta}", lambda: _place_one(server, f"biblio-{i}", entry, x, z))
        else:
            _try(log, f"{item}:{meta} yaw {yaw}", lambda: server.use(OVERWORLD, x, FLOOR_Y, z, "UP", item, meta, yaw))
    # 2x2 tables and a row of shelves
    for dx, dz in ((0, 0), (1, 0), (0, 1), (1, 1)):
        _try(log, "table group", lambda: server.use(OVERWORLD, dx, FLOOR_Y, BIBLIO_GROUP_Z + dz, "UP", "BiblioCraft:BiblioTable", 0, 0))
    for dx in range(3):
        _try(log, "bookcase row", lambda: server.use(OVERWORLD, 4 + dx, FLOOR_Y, BIBLIO_GROUP_Z, "UP", "BiblioCraft:Bibliotheca", 1, 180))


def _ae2(server: Server, log: list) -> None:
    z = AE2_Z
    # controller + drive + chest feeding a line of each cable type with parts on its sides
    _try(log, "controller", lambda: server.use(OVERWORLD, 0, FLOOR_Y, z, "UP", "appliedenergistics2:tile.BlockController", 0))
    _try(log, "drive", lambda: server.use(OVERWORLD, 0, FLOOR_Y, z + 1, "UP", "appliedenergistics2:tile.BlockDrive", 0, 0))
    x = 1
    for cable, base in AE2_CABLES.items():
        for _ in range(4):
            _try(log, f"{cable} cable", lambda: server.use(OVERWORLD, x, FLOOR_Y, z, "UP", AE2_PART, base + FLUIX))
            x += 1
    # parts along a covered cable line at z+3, one part on the north side of each cable block
    x = 0
    for part, meta in AE2_PARTS.items():
        _try(log, f"cable for {part}", lambda: server.use(OVERWORLD, x, FLOOR_Y, z + 3, "UP", AE2_PART, AE2_CABLES["covered"] + FLUIX))
        _try(log, part, lambda: server.use(OVERWORLD, x, Y, z + 3, "NORTH", AE2_PART, meta))
        x += 1
    # a part facing up on a smart cable, and a terminal on a dense cable's top
    _try(log, "smart for up-bus", lambda: server.use(OVERWORLD, 0, FLOOR_Y, z + 5, "UP", AE2_PART, AE2_CABLES["smart"] + FLUIX))
    _try(log, "up import bus", lambda: server.use(OVERWORLD, 0, Y, z + 5, "UP", AE2_PART, AE2_PARTS["import_bus"]))
    # coloured glass cables, unconnected samples
    for colour in range(16):
        _try(log, f"glass cable colour {colour}", lambda: server.use(OVERWORLD, 2 + colour, FLOOR_Y, z + 7, "UP", AE2_PART, AE2_CABLES["glass"] + colour))
        _try(log, f"covered cable colour {colour}", lambda: server.use(OVERWORLD, 2 + colour, FLOOR_Y, z + 8, "UP", AE2_PART, AE2_CABLES["covered"] + colour))
    # a vertical cable riser with a T junction
    for dy in range(3):
        _try(log, "riser", lambda: server.use(OVERWORLD, 20, FLOOR_Y + dy, z, "UP", AE2_PART, AE2_CABLES["smart"] + FLUIX))
    _try(log, "T", lambda: server.use(OVERWORLD, 20, Y + 1, z, "EAST", AE2_PART, AE2_CABLES["smart"] + FLUIX))


def _enderio(server: Server, log: list) -> None:
    z = ENDERIO_Z
    # a 4-long line of each conduit type
    for i, (item, meta) in enumerate(CONDUITS):
        for dx in range(4):
            _try(log, f"{item}:{meta} line", lambda: server.use(OVERWORLD, dx, FLOOR_Y, z + i * 2, "UP", item, meta))
    # a bundle line carrying item + fluid + power + redstone, with an L turn
    bz = z + len(CONDUITS) * 2 + 1
    cells = [(x, bz) for x in range(6)] + [(5, bz + d) for d in range(1, 4)]
    for item, meta in (CONDUITS[0], CONDUITS[1], CONDUITS[4], CONDUITS[7]):
        for cx, cz in cells:
            _try(log, f"bundle {item}", lambda: server.use(OVERWORLD, cx, FLOOR_Y, cz, "UP", item, meta))
    # item conduit into a chest (external connection)
    _try(log, "chest", lambda: server.use(OVERWORLD, 6, FLOOR_Y, z, "UP", "minecraft:chest", 0))


FACADE_Z = ENDERIO_Z + 24
AE2_FACADE = "appliedenergistics2:item.ItemFacade"


def _ae2_facade_tag(block: str, meta: int) -> dict:
    """NBT of an AE2 facade item for ``block:meta`` (as `ItemFacade.createFacadeForItem` writes it; the item id is
    resolved from the registry name by the harness)."""
    modid, name = block.split(":", 1)
    return {"x": {"@ints": [{"@itemId": block}, meta]}, "modid": modid, "itemname": name}


def _facades(server: Server, log: list) -> None:
    """AE2 facades on cable buses and EnderIO conduit-bundle facades, vanilla and modded blocks."""
    z = FACADE_Z
    samples = [("minecraft:stone", 0), ("minecraft:planks", 1), ("minecraft:wool", 14), ("chisel:factoryblock", 4)]
    for i, (block, meta) in enumerate(samples):
        x = i * 3
        # a glass cable with a facade on its north and top sides (right-clicked with a facade item), next to a bare one
        _try(log, f"facade cable {block}", lambda: server.use(OVERWORLD, x, FLOOR_Y, z, "UP", AE2_PART, AE2_CABLES["glass"] + FLUIX))
        _try(log, f"facade cable 2 {block}", lambda: server.use(OVERWORLD, x + 1, FLOOR_Y, z, "UP", AE2_PART, AE2_CABLES["glass"] + FLUIX))
        for side in ("NORTH", "UP"):
            _try(log, f"ae2 facade {block}:{meta} {side}", lambda: server.use(OVERWORLD, x, Y, z, side, AE2_FACADE, 0, tag=_ae2_facade_tag(block, meta)))
        # an item conduit line whose middle bundle carries a facade
        for dx in range(3):
            _try(log, f"facade conduit {block}", lambda: server.use(OVERWORLD, x + dx, FLOOR_Y, z + 3, "UP", "EnderIO:itemItemConduit", 0))
        _try(log, f"eio facade {block}:{meta}", lambda: server.te_nbt(OVERWORLD, x + 1, Y, z + 3, {"facadeId": block, "facadeMeta": meta, "facadeType": "BASIC"}))


def mod_renderers(server: Server) -> dict:
    log: list = []
    x1, z1, x2, z2 = -2, -2, 80, FACADE_Z + 6
    server.bmh("fill", OVERWORLD, x1, FLOOR_Y, z1, x2, FLOOR_Y, z2, "minecraft:stone", 0)
    _chisel(server, log)
    _iron_chests(server, log)
    _bibliocraft(server, log)
    _ae2(server, log)
    _enderio(server, log)
    _facades(server, log)
    errors = [e for e in log if "error" in e]
    _write_in(server, "mod-renderers.json", log)
    return {"placed": len(log) - len(errors), "failed": len(errors), "errors": errors[:50], "dump_box": [x1, FLOOR_Y, z1, x2, Y + 6, z2]}
