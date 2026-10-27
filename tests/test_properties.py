from orchestrator.server import render_properties


def test_overrides_existing_keys_appends_missing_and_keeps_the_rest():
    existing = "#Minecraft server properties\nlevel-name=World\nmotd=GT:New Horizons\nenable-rcon=false\n"
    rendered = render_properties(existing, {"enable-rcon": "true", "level-name": "scene-x", "rcon.port": "25575"})
    assert rendered.splitlines() == [
        "#Minecraft server properties",
        "level-name=scene-x",
        "motd=GT:New Horizons",
        "enable-rcon=true",
        "rcon.port=25575",
    ]
