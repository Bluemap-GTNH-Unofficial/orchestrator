# orchestrator

Headless test orchestration for the BlueMap GTNH port: GTNH server lifecycle, RCON, the `bmh`
harness mod (`testing/harness-mod`) and deterministic scene worlds.

Layout it expects (override the root with `BMGTNH_WORKSPACE`):

```
<workspace>/
  BlueMap-GTNH/testing/orchestrator   # this project
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
uv run orch scene --list                # name, level type, description of every scene
uv run orch scene gt-machines --verify  # ... then ./gradlew :legacy:verifyDump on the snapshot + dump
uv run orch scene all --verify          # every scene in turn; summary JSON; exit 1 if any failed or mismatched
uv run orch verify gt-machines          # verifyDump an already built scene again (result into scene.json)
uv run --group dev pytest
```

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
