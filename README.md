# orchestrator: headless GTNH servers and test scenes

> [!WARNING]
> Unofficial: not affiliated with BlueMap or GT New Horizons. Vibe coded (written largely by an AI coding agent), no
> quality guarantee, use at your own risk. See the
> [umbrella repository](https://github.com/Bluemap-GTNH-Unofficial/BlueMap-GTNH) for details.

Part of [Bluemap-GTNH-Unofficial/BlueMap-GTNH](https://github.com/Bluemap-GTNH-Unofficial/BlueMap-GTNH). Clone the
umbrella with `git clone --recursive`; this repository expects its sibling checkouts (`BlueMap/`, `harness/` and the
workspace folders) next to it.

Headless test orchestration for the BlueMap GTNH port: GTNH server lifecycle, RCON, the `bmh` harness mod (the
sibling [`harness`](https://github.com/Bluemap-GTNH-Unofficial/harness) repository) and deterministic scene worlds,
which the world reader and the e2e suite are tested on.

Layout it expects (override the root with `BMGTNH_WORKSPACE`):

```
<workspace>/                           # default: the parent of this checkout
  orchestrator/                        # this project
  BlueMap/                             # the BlueMap fork (`--verify` runs its :legacy:verifyDump)
  servers/<server>/                    # unpacked GTNH server pack + .rcon-password
  worlds/<snapshot>/                   # world snapshots (created by `orch snapshot` / scenes)
  out/scenes/<scene>/                  # scene outputs: manifests, dumps, registry, scene.json
```

Every `start` rewrites the RCON/port/level keys of `server.properties` and sets `eula=true`;
the RCON password is read from `servers/<server>/.rcon-password`.

```bash
uv run orch start                       # boots, returns once "RCON running" is logged
uv run orch rcon list "save-all"
uv run orch bmh ping                    # prints the JSON payload of `OK {...}`
uv run orch stop
uv run orch --level scene-x --level-type FLAT start
uv run orch snapshot <name> | restore <name> | delete-level | snapshots
uv run orch scene vanilla-zoo           # fresh world -> bmh zoo + dump -> out/ and worlds/
uv run orch scene --list                # name, level type, required server, description of every scene
uv run orch scene gt-machines --verify  # ... then ./gradlew :legacy:verifyDump on the snapshot + dump
uv run orch scene all --verify          # every scene runnable on --server (others printed as skipped); summary
                                        # JSON; exit 1 if any run failed or mismatched
uv run orch verify gt-machines          # verifyDump an already built scene again (result into scene.json)
uv run --group dev pytest
```

From Python, `Server.bmh(*args)` runs any harness subcommand; `Server.te_nbt(dim, x, y, z, patch)` (patch: JSON-patch
dict or SNBT string, written to `bmh-out/te-nbt.{json,snbt}`) and `Server.use(dim, x, y, z, side, item, meta=0,
yaw=None, count=1)` wrap `bmh te-nbt` / `bmh use`. One RCON connection is kept open per `Server` (`close_rcon()`).

Each scene declares the server directories whose mod set it needs (`Scene.servers`): the vanilla, GT and
mod-renderer scenes run on `gtnh-2.9.0-RC-2`, the addon scenes (`addon_scenes.py`) on `gtnh-addons`
(`--server gtnh-addons --port 25568 --rcon-port 25578`). Every scene runs on one kind of server only, so
`out/scenes/<scene>` and `worlds/<scene>` stay unique; `scene <name>` on another server fails before starting it.

Scenes are defined in `src/orchestrator/scenes.py`. Every scene starts from an empty level folder, sets
`doDaylightCycle/doMobSpawning/doFireTick/mobGriefing false`, writes `registry.json`, builds, `bmh hold`s the chunks of
its dump box (so tile entities there tick and settle), waits 15 s, drops the box's scheduled block updates
(`bmh drop-ticks`: lava still flowing in caves would otherwise change after the dump), flushes, dumps its box (`dump.ndjson`, right after
saving so it matches the disk) and stops the server; a crash report written during the run fails it. `scene.json`
holds the bmh replies, `placed`/`failed` counts, `dump_box`, `build_seconds`, `seconds` and, with `--verify`, the
verifyDump result.

| Scene | World | Content |
|---|---|---|
| `vanilla-zoo`, `gtnh-zoo` | FLAT | `bmh zoo minecraft` / `all` |
| `gt-machines` | FLAT | `mtes.json`; every single-block MTE (types machine, hatch, generator, boiler, tank, chest, battery_buffer, transformer, hull, other) via `place-list` facing NORTH (UP/DOWN if it cannot face north); the first MTE of each class that faced north again facing SOUTH, EAST, WEST (`machines-<facing>[-placed].json`) |
| `gt-pipes` | FLAT | every cable/fluid_pipe/item_pipe/pipe/frame MTE as a 3-block line; a T, cross, L and vertical line per cable/fluid/item type and distinct (thickness, insulated, pipeAmount) and per other pipe MTE (painted: TecTech pipes only connect when painted); 17 lines coloured -1..15 for the first cable/fluid/item pipe and every other pipe MTE (`pipes.json`: one record per `bmh pipe` call) |
| `gt-ores` | FLAT | `gt-ores.json`; every material on every `gt.blockores2` stone, normal + small, plus the first material on every stone of `gt.blockores3..7` (`ores[-placed].json`) |
| `gt-multiblocks` | FLAT | `MULTIBLOCKS` (GT, GT++, bartworks, TecTech, kekztech) every 48 blocks along +x at y=20, facing NORTH: `bmh multiblock … survival` (creative for the bricked blast furnace), then hatches the build leaves out placed with `bmh mte` and `multiblock … check`; `formed` per controller in `multiblocks.json` |
| `terrain-rwg` | rwg, seed 1710 | `bmh pregen` of chunks -16..15 in strips of 8 columns; dump of blocks (0,0,0)..(31,255,31) |
| `addons-zoo` | FLAT | needs the community addons (below): `bmh zoo <namespace>` per addon (TST, GTNL, PH, 123T, NHU, Box++) side by side along +x (`zoo-<addon>.json`) |
| `addons-machines` | FLAT | needs the addons: every addon MTE (picked by class package from `mtes.json`, minus `CRASHING_MTES`) via `place-list` facing NORTH, one list per addon along +x (`machines-<addon>[-placed].json`) |
| `addons-multiblocks` | FLAT | needs the addons: `MULTIBLOCKS` of `addon_scenes.py` (survival, Box++ creative) at y=20 spaced by their measured width; a row of addon TESR blocks at z=-48 and a row with effects switched on via `te-nbt` at z=-64 (`multiblocks.json`) |

The `addons-*` scenes (`src/orchestrator/addon_scenes.py`) run on `servers/gtnh-addons`: the reference server plus the
six addon jars of `<workspace>/downloads/addons/versions.json` and two config changes the addons need on RC-2 —
`config/GregTech/GregTech.cfg` `crashOnNullRecipeInput=false` (TST 0.8.0-RC2.9 builds an extreme-crafting recipe from
the empty ore dictionary entry `craftingBlastFurnace` and would crash the load) and
`config/GTNotLeisure/GTNotLeisure.cfg` `enableRecipeOutputChance=false` (GTNL 0.2.7-rc2's mixin into TST's
`GTCM_ParallelHelper` fails against TST RC2.9, making every TST multiblock unloadable). Use
`uv run orch --server gtnh-addons --port 25568 --rcon-port 25578 scene addons-zoo --verify`. They fail fast on a server
without the addons, so `scene all` on the reference server reports them as failed.
