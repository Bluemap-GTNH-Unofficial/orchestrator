import itertools

from orchestrator.scenes import chunk_strips, north_list, ore_list, pipe_plan, sample_list


def _mtes() -> list[dict]:
    mtes = []
    for i in range(37):
        mtes.append({"id": 1000 + i, "type": "cable", "class": "MTECable", "thickness": [0.125, 0.25][i % 2],
                     "insulated": i % 3 == 0})  # fmt: skip
    for i in range(11):
        mtes.append({"id": 5000 + i, "type": "fluid_pipe", "class": "MTEFluidPipe", "thickness": 0.5, "pipeAmount": 1})
    mtes.append({"id": 6000, "type": "frame", "class": "MTEFrame", "thickness": 1.0})
    for i in range(2):
        mtes.append({"id": 8000 + i, "type": "pipe", "class": "MTEPipeData", "thickness": 0.375})
    mtes.append({"id": 7000, "type": "machine", "class": "MTEMacerator"})
    mtes.append({"id": 7001, "type": "multiblock", "class": "MTEElectricBlastFurnace"})
    return mtes


def _neighbours(b):
    x, y, z = b
    return {(x + dx, y + dy, z + dz) for dx, dy, dz in itertools.product((-1, 0, 1), repeat=3)}


def test_pipe_plan_groups_never_touch_and_junction_lines_share_one_block():
    plan = pipe_plan(_mtes())
    # a group is a set of lines that must connect: one junction feature (T, cross, L, vertical) or a single line
    groups: dict[tuple, list] = {}
    junction_index = 0
    for line in plan:
        if line.section == "junction":
            # every representative gets 7 lines: T bar + stem, cross bar + bar, L legs, vertical
            cell, k = divmod(junction_index, 7)
            key = ("junction", cell, (0, 0, 1, 1, 2, 2, 3)[k])
            junction_index += 1
        else:
            key = (line.section, line.start)
        groups.setdefault(key, []).append(line)

    owner: dict[tuple, tuple] = {}
    for key, lines in groups.items():
        for line in lines:
            for b in line.blocks():
                assert owner.get(b, key) == key, f"{b} used by {owner.get(b)} and {key}"
                owner[b] = key
    for b, key in owner.items():
        for n in _neighbours(b):
            assert owner.get(n, key) == key, f"group {key} at {b} touches {owner[n]} at {n}"

    for key, lines in groups.items():
        if key[0] == "junction" and len(lines) == 2:
            assert len(set(lines[0].blocks()) & set(lines[1].blocks())) == 1


def test_pipe_plan_covers_every_pipe_once_and_samples_colours_and_junctions():
    mtes = _mtes()
    plan = pipe_plan(mtes)
    lines = [line.mte for line in plan if line.section == "line"]
    assert sorted(lines) == sorted(e["id"] for e in mtes if e["type"] in ("cable", "fluid_pipe", "frame", "pipe"))
    colours = [(line.mte, line.color) for line in plan if line.section == "color"]
    assert colours == [(m, c) for m in (1000, 5000, 8000, 8001) for c in range(-1, 16)]
    junctions = {(line.mte, line.color) for line in plan if line.section == "junction"}
    # cables: (0.125, insulated), (0.25, not), (0.125, not), (0.25, insulated); fluid: 1; every `pipe` MTE, painted
    assert junctions == {(1000, -1), (1001, -1), (1002, -1), (1003, -1), (5000, -1), (8000, 0), (8001, 0)}


def test_north_list_skips_multiblocks_and_pipes_and_falls_back_to_vertical_facings():
    mtes = _mtes() + [{"id": 7002, "type": "hatch", "class": "MTEHatchInput"}]
    facings = ["NORTH", "UP", "DOWN"]
    assert north_list(mtes) == [{"mte": 7000, "facing": facings}, {"mte": 7002, "facing": facings}]


def test_sample_list_takes_the_first_north_facing_mte_of_each_class():
    mtes = [
        {"id": 1, "type": "machine", "class": "CropManager"},
        {"id": 2, "type": "machine", "class": "Macerator"},
        {"id": 3, "type": "machine", "class": "Macerator"},
        {"id": 4, "type": "machine", "class": "CropManager"},
    ]
    placed = [{"mte": 1, "facing": 1}, {"mte": 2, "facing": 2}, {"mte": 3, "facing": 2}, {"mte": 4, "facing": 1}]
    assert sample_list(mtes, placed, "WEST") == [{"mte": 2, "facing": "WEST"}]


def test_ore_list_has_all_ores2_and_one_sample_per_other_stone_and_size():
    def ore(name, stone, small, meta):
        return {"name": name, "stone": stone, "small": small, "meta": meta}

    ores = [
        ore("gregtech:gt.blockores2", "Stone", False, 6),
        ore("gregtech:gt.blockores2", "Stone", True, 16006),
        ore("gregtech:gt.blockores2", "Basalt", False, 6006),
        ore("gregtech:gt.blockores3", "Mars", False, 6),
        ore("gregtech:gt.blockores3", "Mars", False, 8),
        ore("gregtech:gt.blockores3", "Mars", True, 16008),
    ]
    assert ore_list(ores) == [
        {"name": "gregtech:gt.blockores2", "meta": 6},
        {"name": "gregtech:gt.blockores2", "meta": 16006},
        {"name": "gregtech:gt.blockores2", "meta": 6006},
        {"name": "gregtech:gt.blockores3", "meta": 6},
        {"name": "gregtech:gt.blockores3", "meta": 16008},
    ]


def test_chunk_strips_cover_the_rectangle_exactly_within_the_cap():
    strips = chunk_strips(-3, -2, 60, 4, cap=100)
    covered = [(x, z) for x1, z1, x2, z2 in strips for x in range(x1, x2 + 1) for z in range(z1, z2 + 1)]
    assert sorted(covered) == [(x, z) for x in range(-3, 61) for z in range(-2, 5)]
    assert all((x2 - x1 + 1) * (z2 - z1 + 1) <= 100 for x1, z1, x2, z2 in strips)
    assert len(strips) == 5  # 64 columns of 7 chunks, 14 columns per strip
