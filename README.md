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
uv run --group dev pytest
```

Scenes are defined in `src/orchestrator/scenes.py`.
