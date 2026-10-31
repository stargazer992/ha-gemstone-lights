#!/usr/bin/env python3
"""A fake Gemstone Hub2 controller for testing the integration without hardware.

Serves the three local API routes the integration uses, over a real socket:

    GET  /device-state/hub-settings
    GET  /device-state/currently-playing
    POST /device-control/play

Several controllers can run at once, each on its own address. The integration
only takes a host (port 80), so give each fake its own loopback address; binding
port 80 needs root or CAP_NET_BIND_SERVICE:

    sudo .venv/bin/python tools/gemstone_sim.py \\
        --controller "Front House@127.0.0.2" --controller "Pool House@127.0.0.3"

Then add each controller in Home Assistant with Set up a local controller,
using its address. Open http://<address>/_sim for a control panel and live
request log. Everything there is also scriptable over HTTP:

    GET  /_sim/status                  state, settings, fault and recent requests
    POST /_sim/fault    {"mode": ...}  normal | busy | busy-once | slow | down | lossy
                        {"seconds": n} how long "slow" stalls (default 10, past the 8 s timeout)
                        {"rate": 0.3}  share of requests "lossy" drops
    POST /_sim/external                change the colour as if from the Gemstone app
    POST /_sim/power-cycle {"seconds": n}  unreachable for n seconds, then lights off

Commands are checked against the API document's bounds and rejected with 400 if
out of range. That is stricter than firmware may be, so a client bug fails here
rather than silently on the roofline. It does not model Bluetooth, the cloud
import, or what the lights actually look like.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
import uuid
from collections import deque
from copy import deepcopy
from typing import Any

from aiohttp import web

SCENES = ("color", "colorB", "pattern", "architectural", "impulse", "playlist")
FAULTS = ("normal", "busy", "busy-once", "slow", "down", "lossy")
MAX_BODY = 15 * 1024
U32 = 0xFFFFFFFF
EXTERNAL_COLORS = (255, 65280, 16711680, 4278190080, 12614435)


def _int(value: Any, low: int, high: int) -> bool:
    return (
        isinstance(value, int) and not isinstance(value, bool) and low <= value <= high
    )


def check_command(playing: Any) -> str | None:
    """Return why a ``currentlyPlaying`` command is invalid, or None."""
    if not isinstance(playing, dict):
        return "currentlyPlaying must be an object"
    active = [key for key in SCENES if playing.get(key) is not None]
    if len(active) > 1:
        return f"only one scene may be set, got {active}"
    if "onState" in playing and not isinstance(playing["onState"], bool):
        return "onState must be a boolean"
    if (color := playing.get("colorB")) is not None:
        if not isinstance(color, dict) or not _int(color.get("value"), 0, U32):
            return "colorB.value must be a 32-bit RGBW integer"
        if not _int(color.get("brightness"), 0, 255):
            return "colorB.brightness must be 0-255"
    if (pattern := playing.get("pattern")) is not None:
        if not isinstance(pattern, dict):
            return "pattern must be an object"
        name = pattern.get("name")
        if not isinstance(name, str) or not 1 <= len(name) <= 32:
            return "pattern.name must be 1-32 characters"
        if not isinstance(pattern.get("animation"), str):
            return "pattern.animation must be a string"
        colors = pattern.get("colors")
        if not isinstance(colors, list) or not 1 <= len(colors) <= 20:
            return "pattern.colors must hold 1-20 colours"
        if not all(_int(c, 0, U32) for c in colors):
            return "pattern.colors must be 32-bit RGBW integers"
        for key, low, high in (
            ("brightness", 0, 255),
            ("speed", 1, 255),
            ("direction", 0, 5),
            ("backgroundColor", 0, U32),
        ):
            if key in pattern and not _int(pattern[key], low, high):
                return f"pattern.{key} must be {low}-{high}"
        if "extraParameters" in pattern:
            extras = pattern["extraParameters"]
            if not isinstance(extras, dict) or not _int(
                extras.get("version"), 0, 65535
            ):
                return "pattern.extraParameters needs a version"
            for key, entry in extras.items():
                if key == "version":
                    continue
                if not key.isdigit() or not isinstance(entry, dict):
                    return f"pattern.extraParameters[{key!r}] is malformed"
                if not _int(entry.get("value"), 0, U32):
                    return f"pattern.extraParameters[{key}].value must be an integer"
    if (design := playing.get("architectural")) is not None:
        if not isinstance(design, dict):
            return "architectural must be an object"
        if "brightness" in design and not _int(design["brightness"], 0, 255):
            return "architectural.brightness must be 0-255"
    return None


class FakeController:
    """One controller: what it shows, its settings, and any injected fault."""

    def __init__(self, name: str, host: str, port: int = 80, pixels: int = 150) -> None:
        self.name = name
        self.host = host
        self.port = port
        self.serial = f"h2-sim-{uuid.uuid4().hex[:4]}"
        self.settings: dict[str, Any] = {
            "pixelCount": [pixels, 0, 0, 0],
            "outputNames": [name, "", "", ""],
            "reversePixels": [False, False, False, False],
            "rgbwSequence": "RGBW",
            "localIp": host,
            "tcpEnabled": True,
            "bluetoothName": name,
            "firmware": "1.1.5",
        }
        self.playing: dict[str, Any] = {
            "onState": True,
            "colorB": {"value": 12614435, "brightness": 200},
            "pattern": None,
            "architectural": None,
        }
        self.fault = "normal"
        self.slow_seconds = 10.0
        self.loss_rate = 0.3
        self.down_until = 0.0
        self.log: deque[dict[str, Any]] = deque(maxlen=100)
        self._external = 0

    def record(self, method: str, path: str, status: int, note: str = "") -> None:
        self.log.appendleft(
            {
                "time": time.strftime("%H:%M:%S"),
                "method": method,
                "path": path,
                "status": status,
                "note": note,
            }
        )

    def apply(self, command: dict[str, Any]) -> None:
        if any(key in command for key in SCENES):
            for key in SCENES:
                self.playing[key] = deepcopy(command.get(key))
        if "onState" in command:
            self.playing["onState"] = command["onState"]

    def external_change(self) -> int:
        """Imitate someone changing the colour in the Gemstone app."""
        color = EXTERNAL_COLORS[self._external % len(EXTERNAL_COLORS)]
        self._external += 1
        self.apply({"onState": True, "colorB": {"value": color, "brightness": 255}})
        return color

    def power_cycle(self, seconds: float) -> None:
        self.down_until = time.monotonic() + seconds
        self.playing["onState"] = False

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "address": f"{self.host}:{self.port}",
            "fault": self.fault,
            "down": time.monotonic() < self.down_until,
            "currentlyPlaying": self.playing,
            "hubSettings": self.settings,
            "requests": list(self.log),
        }


def _shadow(key: str, value: Any, origin: str = "http") -> dict[str, Any]:
    return {"state": {"reported": {key: value, "origin": origin}}}


PANEL = """<!doctype html><meta charset=utf-8><title>Fake Gemstone</title>
<style>body{font:14px system-ui;margin:2em}button{margin:2px}pre{background:#f4f4f4;padding:1em}</style>
<h1 id=t></h1><p>Fault:
<span id=f></span></p><p id=b></p>
<button onclick="post('external')">Change colour from app</button>
<button onclick="post('power-cycle',{seconds:60})">Power cycle 60 s</button>
<pre id=s></pre><script>
const F=%s;
document.getElementById('b').innerHTML=F.map(m=>`<button onclick="post('fault',{mode:'${m}'})">${m}</button>`).join('');
async function post(p,b){await fetch('/_sim/'+p,{method:'POST',body:JSON.stringify(b||{})});load()}
async function load(){const s=await (await fetch('/_sim/status')).json();
document.getElementById('t').textContent=s.name+' ('+s.address+')';
document.getElementById('f').textContent=s.fault+(s.down?' (powering up)':'');
document.getElementById('s').textContent=JSON.stringify(s,null,2)}
load();setInterval(load,2000)</script>""" % json.dumps(FAULTS)


def build_app(sim: FakeController) -> web.Application:
    """The HTTP app for one fake controller."""

    async def faults(request: web.Request) -> web.StreamResponse | None:
        if (
            time.monotonic() < sim.down_until
            or sim.fault == "down"
            or (sim.fault == "lossy" and random.random() < sim.loss_rate)
        ):
            sim.record(request.method, request.path, 0, "dropped")
            if request.transport is not None:
                request.transport.close()
            raise asyncio.CancelledError
        if sim.fault == "slow":
            sim.record(
                request.method, request.path, 0, f"stalled {sim.slow_seconds:g}s"
            )
            await asyncio.sleep(sim.slow_seconds)
        if sim.fault in ("busy", "busy-once"):
            if sim.fault == "busy-once":
                sim.fault = "normal"
            sim.record(request.method, request.path, 503, "busy")
            return web.Response(status=503, text="Service temporarily unavailable")
        return None

    async def hub_settings(request: web.Request) -> web.StreamResponse:
        if (fault := await faults(request)) is not None:
            return fault
        sim.record("GET", request.path, 200)
        return web.json_response(_shadow("hubSettings", sim.settings))

    async def currently_playing(request: web.Request) -> web.StreamResponse:
        if (fault := await faults(request)) is not None:
            return fault
        sim.record("GET", request.path, 200)
        return web.json_response(_shadow("currentlyPlaying", sim.playing))

    async def play(request: web.Request) -> web.StreamResponse:
        if (fault := await faults(request)) is not None:
            return fault
        if request.content_type != "application/json":
            sim.record("POST", request.path, 415)
            return web.Response(status=415, text="Only application/json is supported")
        raw = await request.read()
        if len(raw) > MAX_BODY:
            sim.record("POST", request.path, 413)
            return web.Response(status=413, text="Request entity too large")
        try:
            desired = json.loads(raw)["state"]["desired"]
            command = desired["currentlyPlaying"]
        except ValueError, KeyError, TypeError:
            sim.record("POST", request.path, 400, "malformed")
            return web.Response(status=400, text="Malformed request")
        if (problem := check_command(command)) is not None:
            sim.record("POST", request.path, 400, problem)
            return web.Response(status=400, text=problem)
        sim.apply(command)
        sim.record("POST", request.path, 200, json.dumps(command)[:200])
        return web.json_response(
            _shadow("currentlyPlaying", sim.playing, desired.get("origin", "http"))
        )

    async def wrong_method(request: web.Request) -> web.StreamResponse:
        return web.Response(status=405, text="Only GET and POST are supported")

    async def panel(request: web.Request) -> web.StreamResponse:
        return web.Response(text=PANEL, content_type="text/html")

    async def status(request: web.Request) -> web.StreamResponse:
        return web.json_response(sim.status())

    async def _body(request: web.Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    async def set_fault(request: web.Request) -> web.StreamResponse:
        body = await _body(request)
        if body.get("mode") not in FAULTS:
            return web.json_response(
                {"error": f"mode must be one of {FAULTS}"}, status=400
            )
        sim.fault = body["mode"]
        sim.slow_seconds = float(body.get("seconds", sim.slow_seconds))
        sim.loss_rate = float(body.get("rate", sim.loss_rate))
        return web.json_response(sim.status())

    async def external(request: web.Request) -> web.StreamResponse:
        sim.external_change()
        return web.json_response(sim.status())

    async def power_cycle(request: web.Request) -> web.StreamResponse:
        sim.power_cycle(float((await _body(request)).get("seconds", 60)))
        return web.json_response(sim.status())

    app = web.Application()
    app.router.add_get("/device-state/hub-settings", hub_settings)
    app.router.add_get("/device-state/currently-playing", currently_playing)
    app.router.add_post("/device-control/play", play)
    for path in (
        "/device-state/hub-settings",
        "/device-state/currently-playing",
        "/device-control/play",
    ):
        app.router.add_route("*", path, wrong_method)
    app.router.add_get("/_sim", panel)
    app.router.add_get("/_sim/status", status)
    app.router.add_post("/_sim/fault", set_fault)
    app.router.add_post("/_sim/external", external)
    app.router.add_post("/_sim/power-cycle", power_cycle)
    return app


def parse_controller(spec: str) -> FakeController:
    """Parse ``Name@host[:port]``."""
    name, _, address = spec.rpartition("@")
    host, _, port = address.partition(":")
    return FakeController(name or host, host, int(port or 80))


async def serve(controllers: list[FakeController]) -> None:
    runners = []
    for sim in controllers:
        runner = web.AppRunner(build_app(sim), access_log=None)
        await runner.setup()
        await web.TCPSite(runner, sim.host, sim.port).start()
        runners.append(runner)
        print(f"{sim.name}: http://{sim.host}:{sim.port}/_sim")
    try:
        await asyncio.Event().wait()
    finally:
        for runner in runners:
            await runner.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--controller",
        action="append",
        metavar="NAME@HOST[:PORT]",
        help="a fake controller to run (repeatable); default 'Gemstone Sim@127.0.0.2'",
    )
    args = parser.parse_args()
    controllers = [
        parse_controller(spec) for spec in args.controller or ["Gemstone Sim@127.0.0.2"]
    ]
    try:
        asyncio.run(serve(controllers))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
