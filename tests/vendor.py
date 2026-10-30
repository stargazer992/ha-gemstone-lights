"""Stateful external HTTP boundary used by behavior tests."""

import json
import re
from copy import deepcopy

from aioresponses import CallbackResult


class Vendor:
    """Emulate only vendor network responses, never integration helpers."""

    def __init__(self, http):
        self.devices = [
            {
                "id": "hub",
                "name": "House",
                "online": True,
                "hub": {"localIp": "192.0.2.10", "tcpEnabled": True},
            }
        ]
        self.states = {"hub": {"onState": True, "color": 255}}
        self.zones = {
            "hub": [
                {"id": "front", "name": "Front", "lights": [10, 11, 12]},
                {"id": "back", "name": "Back", "lights": [13, 14, 15]},
            ]
        }
        self.designs = []
        self.folders = []
        self.library_folders = []
        self.library_patterns = []
        self.reads_waiting = 0
        self.patterns = {}
        self.writes = []
        self.failures = {}
        self.cloud_offline = False
        self.echo_writes = True
        self.first_write_started = None
        self.release_first_write = None
        # Set to an unset asyncio.Event to stall LAN state reads until it is set.
        self.hold_reads = None
        cloud = re.compile(
            r"https://mytpybpq12\.execute-api\.us-west-2\.amazonaws\.com/.*"
        )
        local = re.compile(r"http://192\.0\.2\.\d+/.*")
        http.get(cloud, callback=self.cloud, repeat=True)
        http.put(cloud, callback=self.cloud, repeat=True)
        http.post(cloud, callback=self.cloud, repeat=True)
        http.get(local, callback=self.local, repeat=True)
        http.post(local, callback=self.local, repeat=True)

    async def cloud(self, url, **kwargs):
        path = url.path.removeprefix("/prod")
        query_path = f"{path}?{url.query_string}"
        if query_path in self.failures:
            return CallbackResult(status=self.failures[query_path])
        if self.cloud_offline or path in self.failures:
            return CallbackResult(status=self.failures.get(path, 503))
        device = url.query.get("deviceOrGroupId", url.query.get("deviceId", "hub"))
        if path == "/deviceControl/softReboot":
            self.writes.append(("cloud", device, path, dict(url.query)))
            return CallbackResult(payload={"data": None})
        if "json" in kwargs and kwargs["json"] is not None:
            body = deepcopy(kwargs["json"])
            self.writes.append(("cloud", device, path, body))
            if path == "/deviceControl/deviceSettings":
                for info in self.devices:
                    if info["id"] == device:
                        info.setdefault("hub", {}).update(body)
            if len(self.writes) == 1 and self.release_first_write is not None:
                self.first_write_started.set()
                await self.release_first_write.wait()
            if self.echo_writes and path != "/deviceControl/deviceSettings":
                if "onState" in body:
                    self.states.setdefault(device, {}).update(body)
                else:
                    self.states[device] = {"onState": True, **deepcopy(body)}
                    design = self.states[device].get("architectural") or {}
                    if design.get("zonePatterns"):
                        # Observed on Hub2 1.1.5: cloud play copies the master
                        # brightness into every nested pattern's reported level.
                        design.setdefault("staticColors", [])
                        for entry in design["zonePatterns"]:
                            entry["pattern"]["brightness"] = design.get(
                                "brightness", 255
                            )
            return CallbackResult(payload={"data": None})
        data = {
            "/homegroup/list": [{"id": "home"}],
            "/homegroup/devices": self.devices,
            "/deviceControl/currentlyPlaying": self.states.get(
                device, {"onState": False}
            ),
            "/deviceControl/zone/list": self.zones.get(device, []),
            "/deviceControl/architectural/list": self.designs,
            "/folders/list": self.folders,
            "/folders/pattern/list": self.patterns.get(url.query.get("folderId"), []),
            "/downloads/folders/listGemstoneManaged": self.library_folders,
            "/downloads/folders/pattern/listGemstoneManaged": self.library_patterns,
        }[path]
        return CallbackResult(payload={"data": deepcopy(data)})

    async def local(self, url, **kwargs):
        if url.path in self.failures:
            return CallbackResult(status=self.failures[url.path])
        device = next(
            (
                d["id"]
                for d in self.devices
                if (d.get("hub") or {}).get("localIp") == url.host
            ),
            "hub",
        )
        if "data" in kwargs:
            playing = json.loads(kwargs["data"])["state"]["desired"]["currentlyPlaying"]
            self.writes.append(("local", device, url.path, deepcopy(playing)))
            if len(self.writes) == 1 and self.release_first_write is not None:
                self.first_write_started.set()
                await self.release_first_write.wait()
            native_zones = (playing.get("architectural") or {}).get(
                "zonePatterns"
            ) or []
            missing_identity = any(
                not (zone.get("pattern") or {}).get("id")
                or not (zone.get("pattern") or {}).get("name")
                for zone in native_zones
            )
            # Hub2 1.1.5 acknowledges but does not apply native zone patterns
            # without identity fields (observed during 1.6.0 candidate testing).
            if self.echo_writes and not missing_identity:
                self.states.setdefault(device, {}).update(playing)
            return CallbackResult(status=200)
        if self.hold_reads is not None:
            self.reads_waiting += 1
            await self.hold_reads.wait()
            self.reads_waiting -= 1
        key = (
            "currentlyPlaying"
            if url.path.endswith("currently-playing")
            else "hubSettings"
        )
        data = (
            self.states[device] if key == "currentlyPlaying" else {"firmware": "1.1.5"}
        )
        return CallbackResult(payload={"state": {"reported": {key: deepcopy(data)}}})
