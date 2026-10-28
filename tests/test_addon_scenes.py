from orchestrator.addon_scenes import (
    ACTIVE_TESR_Z,
    ACTIVE_TESRS,
    ADDONS,
    CRASHING_MTES,
    MULTIBLOCK_BOX_Z,
    MULTIBLOCK_GAP,
    MULTIBLOCKS,
    TESR_BLOCKS,
    TESR_SPACING,
    TESR_Z,
    addon_mtes,
    multiblock_xs,
)
from orchestrator.scenes import SCENES


def test_multiblock_structures_keep_the_gap_between_neighbours():
    xs = multiblock_xs()
    assert xs[0] == 0 and len(xs) == len(MULTIBLOCKS)
    for (x1, a), (x2, b) in zip(zip(xs, MULTIBLOCKS), zip(xs[1:], MULTIBLOCKS[1:]), strict=False):
        assert (x2 - b.west) - (x1 + a.east) == MULTIBLOCK_GAP


def test_tesr_rows_stay_clear_of_the_structures_and_of_each_other():
    assert TESR_Z < MULTIBLOCK_BOX_Z[0]
    assert ACTIVE_TESR_Z + max(t.dz for t in ACTIVE_TESRS) < TESR_Z
    cells = [(t.x, ACTIVE_TESR_Z + t.dz) for t in ACTIVE_TESRS]
    cells += [(TESR_SPACING * i, TESR_Z) for i in range(len(TESR_BLOCKS))]
    assert len(set(cells)) == len(cells)


def test_addon_mtes_picks_by_package_and_skips_crashing_ones():
    crashing = next(iter(CRASHING_MTES))
    mtes = [
        {"id": 1, "class": "gregtech.common.tileentities.machines.MTEHull"},
        {"id": 2, "class": "com.science.gtnl.common.machine.hatch.DualInputHatch"},
        {"id": crashing, "class": "com.science.gtnl.common.machine.multiblock.module.Module"},
        {"id": 4, "class": "com.Nxer.TwistSpaceTechnology.common.machine.TST_ArtificialStar"},
        {"id": 5, "class": "com.sciencey.other.Thing"},
    ]
    by_key = {a.key: a for a in ADDONS}
    assert [e["id"] for e in addon_mtes(mtes, by_key["gtnl"])] == [2]
    assert [e["id"] for e in addon_mtes(mtes, by_key["tst"])] == [4]
    assert addon_mtes(mtes, by_key["boxpp"]) == []


def test_addon_scenes_are_registered_as_superflat_scenes():
    for name in ("addons-zoo", "addons-machines", "addons-multiblocks"):
        assert SCENES[name].level_type == "FLAT"
