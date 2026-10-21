"""An explicit recovery re-arm preserves controller state and reboot safeguards."""

import asyncio
import json
import re
import threading
from copy import deepcopy
from datetime import timedelta

import pytest
from homeassistant.core import Context, CoreState
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.helpers import json as json_helper
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.file import WriteError
from homeassistant.util.json import SerializationError

from custom_components.gemstone_lights.const import API_BASE_URL
from custom_components.gemstone_lights.storage import GemstoneStore

from .test_recovery import failed_probe, reboots

# Retain HA's real serialization/executor path before hass_storage replaces its
# final write with an in-memory fixture. Failure tests must exercise Store's
# normal error handler, which otherwise hides these failures from callers.
_REAL_STORE_WRITE = Store._async_write_data


async def rearm(hass):
    await hass.services.async_call(
        "gemstone_lights",
        "rearm_recovery",
        {"controller": "light.house"},
        blocking=True,
    )


def recovery_attributes(hass):
    return hass.states.get("sensor.house_now_playing").attributes


async def test_rearm_persists_without_controller_or_preference_changes(
    hass, entry, loaded_entry, vendor, http, freezer
):
    # Given a consumed reboot attempt and a locally saved custom pattern.
    await loaded_entry.catalog.save(
        "hub", "pattern", "Keep me", {"colors": [65280], "speed": 42}
    )
    await loaded_entry.async_soft_reboot("hub")
    await failed_probe(loaded_entry, vendor, freezer, 2)
    last_attempt = loaded_entry.recovery.history["hub"]["last_attempt"]
    before_state = deepcopy(vendor.states)
    before_catalog = loaded_entry.catalog.export("hub")
    before_options = dict(entry.options)
    http.requests.clear()
    vendor.writes.clear()

    # When an administrator re-arms recovery while automatic recovery is disabled.
    await rearm(hass)

    # Then only the outage latch and failed-probe window clear, with no network I/O.
    assert not http.requests
    assert not vendor.writes
    assert vendor.states == before_state
    assert loaded_entry.catalog.export("hub") == before_catalog
    assert entry.options == before_options
    assert not loaded_entry._auto_recovery
    assert not loaded_entry._enable_local
    assert loaded_entry.recovery.history["hub"] == {
        "last_attempt": last_attempt,
        "attempted_outage": False,
    }
    assert "hub" not in loaded_entry.recovery.failures
    assert recovery_attributes(hass)["recovery_status"] == "disabled"
    assert recovery_attributes(hass)["recovery_failed_probes"] == 0

    # The explicit re-arm and its cooldown survive a real config-entry reload.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.recovery.history["hub"] == {
        "last_attempt": last_attempt,
        "attempted_outage": False,
    }
    assert entry.runtime_data.catalog.export("hub") == before_catalog
    assert vendor.states == before_state
    assert not vendor.writes


async def test_rearm_explains_cooldown_and_cannot_skip_it(
    hass, loaded_entry, vendor, freezer
):
    loaded_entry._auto_recovery = True
    for _ in range(3):
        await failed_probe(loaded_entry, vendor, freezer, 6)
    assert len(reboots(vendor)) == 1
    attrs = recovery_attributes(hass)
    assert attrs["recovery_status"] == "exhausted"
    last_attempt = dt_util.parse_datetime(attrs["recovery_last_attempt"])
    cooldown_until = dt_util.parse_datetime(attrs["recovery_cooldown_until"])
    assert cooldown_until - last_attempt == timedelta(hours=6)

    await rearm(hass)
    attrs = recovery_attributes(hass)
    assert attrs["recovery_status"] == "cooldown"
    assert dt_util.parse_datetime(attrs["recovery_last_attempt"]) == last_attempt
    assert dt_util.parse_datetime(attrs["recovery_cooldown_until"]) == cooldown_until
    assert attrs["recovery_failure_since"] is None
    assert attrs["recovery_failed_probes"] == 0
    for _ in range(3):
        await failed_probe(loaded_entry, vendor, freezer, 6)
    assert len(reboots(vendor)) == 1
    freezer.tick(timedelta(hours=6))
    await loaded_entry.async_refresh()
    assert len(reboots(vendor)) == 2
    assert recovery_attributes(hass)["recovery_status"] == "exhausted"


async def test_rearm_in_local_only_mode_does_not_enable_cloud_or_recovery(
    hass, entry, loaded_entry, vendor, http, freezer
):
    await loaded_entry.async_soft_reboot("hub")
    await failed_probe(loaded_entry, vendor, freezer, 2)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        flow["flow_id"], {"local_only": True, "auto_recovery": True}
    )
    await hass.async_block_till_done()
    before_options = dict(entry.options)
    http.requests.clear()
    vendor.writes.clear()

    await rearm(hass)

    assert not http.requests
    assert not vendor.writes
    assert entry.options == before_options
    assert entry.runtime_data.api is None
    assert not entry.runtime_data._auto_recovery
    assert not entry.runtime_data._enable_local
    assert not entry.runtime_data.recovery.history["hub"]["attempted_outage"]


async def test_rearm_after_cooldown_requires_new_sustained_failure(
    hass, loaded_entry, vendor, freezer
):
    loaded_entry._auto_recovery = True
    for _ in range(3):
        await failed_probe(loaded_entry, vendor, freezer, 6)
    await failed_probe(loaded_entry, vendor, freezer, 400)
    assert len(reboots(vendor)) == 1
    assert recovery_attributes(hass)["recovery_status"] == "exhausted"

    await rearm(hass)
    assert recovery_attributes(hass)["recovery_status"] == "monitoring"
    assert len(reboots(vendor)) == 1
    await failed_probe(loaded_entry, vendor, freezer, 1)
    attrs = recovery_attributes(hass)
    assert attrs["recovery_status"] == "waiting"
    assert attrs["recovery_failed_probes"] == 1
    assert dt_util.parse_datetime(attrs["recovery_failure_since"]) == dt_util.utcnow()
    await failed_probe(loaded_entry, vendor, freezer, 5)
    assert len(reboots(vendor)) == 1
    await failed_probe(loaded_entry, vendor, freezer, 5)
    assert len(reboots(vendor)) == 2


async def test_rearm_keeps_cloud_preflight_and_reports_local_recovery(
    hass, loaded_entry, vendor, freezer
):
    loaded_entry._auto_recovery = True
    await loaded_entry.async_soft_reboot("hub")
    await failed_probe(loaded_entry, vendor, freezer, 400)
    await rearm(hass)
    vendor.devices[0]["online"] = False
    for _ in range(3):
        await failed_probe(loaded_entry, vendor, freezer, 6)
    # Being eligible to attempt recovery still requires a fresh online confirmation.
    assert len(reboots(vendor)) == 1
    assert recovery_attributes(hass)["recovery_status"] == "ready"
    vendor.devices[0]["online"] = True
    vendor.failures.clear()
    freezer.tick(timedelta(minutes=2))
    await loaded_entry.async_refresh()
    assert recovery_attributes(hass)["recovery_status"] == "local_available"
    assert recovery_attributes(hass)["recovery_failed_probes"] == 0
    assert loaded_entry.control_transport("hub") == "local"


async def test_failed_rearm_storage_leaves_recovery_exhausted(
    hass, loaded_entry, vendor, freezer, monkeypatch, http
):
    loaded_entry._auto_recovery = True
    await loaded_entry.async_soft_reboot("hub")
    await failed_probe(loaded_entry, vendor, freezer, 400)
    before_history = deepcopy(loaded_entry.recovery.history)
    before_failures = deepcopy(loaded_entry.recovery.failures)
    original_save = Store.async_save

    async def failed_save(store, data):
        if store is loaded_entry._store:
            raise OSError("Disk unavailable")
        await original_save(store, data)

    with monkeypatch.context() as patcher:
        patcher.setattr(Store, "async_save", failed_save)
        http.requests.clear()
        with pytest.raises(HomeAssistantError, match="recovery limits unchanged"):
            await rearm(hass)
        assert not http.requests
    assert loaded_entry.recovery.history == before_history
    assert loaded_entry.recovery.failures == before_failures
    assert recovery_attributes(hass)["recovery_status"] == "exhausted"
    for _ in range(3):
        await failed_probe(loaded_entry, vendor, freezer, 6)
    assert len(reboots(vendor)) == 1
    # The same action remains usable after storage recovers.
    await rearm(hass)
    assert recovery_attributes(hass)["recovery_status"] == "monitoring"


@pytest.mark.parametrize("existing_attempt", [False, True])
async def test_failed_reboot_storage_does_not_consume_an_unsent_attempt(
    loaded_entry, vendor, freezer, monkeypatch, existing_attempt
):
    if existing_attempt:
        await loaded_entry.async_soft_reboot("hub")
        await failed_probe(loaded_entry, vendor, freezer, 420)
    history_before = deepcopy(loaded_entry.recovery.history)
    reboot_count = len(reboots(vendor))
    original_save = Store.async_save

    async def failed_save(store, data):
        if store is loaded_entry._store:
            raise OSError("Disk unavailable")
        await original_save(store, data)

    with monkeypatch.context() as patcher:
        patcher.setattr(Store, "async_save", failed_save)
        with pytest.raises(HomeAssistantError, match="no reboot sent"):
            await loaded_entry.async_soft_reboot("hub")
    assert len(reboots(vendor)) == reboot_count
    assert loaded_entry.recovery.history == history_before
    # No phantom two-minute guard blocks a real attempt once saving works again.
    await loaded_entry.async_soft_reboot("hub")
    assert len(reboots(vendor)) == reboot_count + 1


async def test_rearm_serializes_with_reboot_and_keeps_manual_guard(
    hass, loaded_entry, vendor, http
):
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_reboot(url, **kwargs):
        started.set()
        await release.wait()
        return await vendor.cloud(url, **kwargs)

    # Replace the external HTTP routes so the broad vendor POST matcher cannot
    # consume this response before its deliberate in-flight pause.
    http.clear()
    http.get(
        re.compile(re.escape(API_BASE_URL) + r"/.*"), callback=vendor.cloud, repeat=True
    )
    http.get(
        re.compile(r"http://192\.0\.2\.\d+/.*"), callback=vendor.local, repeat=True
    )
    http.post(
        f"{API_BASE_URL}/deviceControl/softReboot?deviceId=hub&homegroupId=home",
        callback=slow_reboot,
    )
    reboot_task = asyncio.create_task(loaded_entry.async_soft_reboot("hub"))
    await asyncio.wait_for(started.wait(), timeout=5)
    rearm_task = asyncio.create_task(rearm(hass))
    try:
        await asyncio.sleep(0)
        assert not rearm_task.done()
    finally:
        release.set()
        await asyncio.gather(reboot_task, rearm_task)
    with pytest.raises(HomeAssistantError, match="two minutes"):
        await loaded_entry.async_soft_reboot("hub")
    assert len(reboots(vendor)) == 1
    assert not loaded_entry.recovery.history["hub"]["attempted_outage"]


@pytest.mark.parametrize("controller", ["light.house_front", "light.missing"])
async def test_rearm_rejects_zone_or_missing_controller(
    hass, loaded_entry, vendor, http, controller
):
    await loaded_entry.async_soft_reboot("hub")
    before = deepcopy(loaded_entry.recovery.history)
    http.requests.clear()
    with pytest.raises(HomeAssistantError, match="whole-controller light"):
        await hass.services.async_call(
            "gemstone_lights",
            "rearm_recovery",
            {"controller": controller},
            blocking=True,
        )
    assert loaded_entry.recovery.history == before
    assert not http.requests
    assert len(reboots(vendor)) == 1


async def test_rearm_requires_administrator(
    hass, loaded_entry, hass_read_only_user, vendor, http
):
    await loaded_entry.async_soft_reboot("hub")
    before = deepcopy(loaded_entry.recovery.history)
    http.requests.clear()
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "gemstone_lights",
            "rearm_recovery",
            {"controller": "light.house"},
            context=Context(user_id=hass_read_only_user.id),
            blocking=True,
        )
    assert loaded_entry.recovery.history == before
    assert not http.requests
    assert len(reboots(vendor)) == 1


@pytest.mark.parametrize("action", ["rearm", "reboot"])
@pytest.mark.parametrize("failure", ["write", "serialization"])
async def test_real_store_failure_cannot_report_success_or_send_reboot(
    hass,
    entry,
    loaded_entry,
    vendor,
    freezer,
    monkeypatch,
    hass_storage,
    action,
    failure,
):
    await loaded_entry.async_soft_reboot("hub")
    await failed_probe(loaded_entry, vendor, freezer, 420)
    before_history = deepcopy(loaded_entry.recovery.history)
    before_failures = deepcopy(loaded_entry.recovery.failures)
    storage_key = f"gemstone_lights.{entry.entry_id}"
    before_stored = deepcopy(hass_storage[storage_key])
    fixture_write = Store._async_write_data
    original_prepare = json_helper.prepare_save_json
    original_write_prepared = Store._write_prepared_data
    failures_seen = []

    async def real_subject_write(store, data):
        if store is loaded_entry._store:
            await _REAL_STORE_WRITE(store, data)
        else:
            await fixture_write(store, data)

    def failed_write_prepared(store, mode, json_data):
        if store is loaded_entry._store:
            failures_seen.append("write")
            raise WriteError("Disk full")
        original_write_prepared(store, mode, json_data)

    def failed_prepare(data, **kwargs):
        if isinstance(data, dict) and data.get("key") == storage_key:
            failures_seen.append("serialization")
            raise SerializationError("Invalid JSON data")
        return original_prepare(data, **kwargs)

    async def perform_action():
        if action == "rearm":
            await rearm(hass)
        else:
            await loaded_entry.async_soft_reboot("hub")

    vendor.writes.clear()
    with monkeypatch.context() as patcher:
        patcher.setattr(Store, "_async_write_data", real_subject_write)
        if failure == "write":
            patcher.setattr(Store, "_write_prepared_data", failed_write_prepared)
        else:
            patcher.setattr(json_helper, "prepare_save_json", failed_prepare)
        message = "recovery limits unchanged" if action == "rearm" else "no reboot sent"
        with pytest.raises(HomeAssistantError, match=message):
            await perform_action()

    assert failure in failures_seen
    assert not vendor.writes
    assert loaded_entry.recovery.history == before_history
    assert loaded_entry.recovery.failures == before_failures
    assert hass_storage[storage_key] == before_stored
    await perform_action()
    if action == "rearm":
        assert not loaded_entry.recovery.history["hub"]["attempted_outage"]
        assert not vendor.writes
    else:
        assert len(reboots(vendor)) == 1


@pytest.mark.parametrize("action", ["rearm", "reboot"])
async def test_shutdown_does_not_treat_deferred_save_as_persisted(
    hass, loaded_entry, vendor, freezer, monkeypatch, action
):
    await loaded_entry.async_soft_reboot("hub")
    await failed_probe(loaded_entry, vendor, freezer, 420)
    before_history = deepcopy(loaded_entry.recovery.history)
    before_failures = deepcopy(loaded_entry.recovery.failures)
    vendor.writes.clear()
    with monkeypatch.context() as patcher:
        patcher.setattr(hass, "state", CoreState.stopping)
        message = "recovery limits unchanged" if action == "rearm" else "no reboot sent"
        with pytest.raises(HomeAssistantError, match=message):
            if action == "rearm":
                await loaded_entry.async_rearm_recovery("hub")
            else:
                await loaded_entry.async_soft_reboot("hub")
    assert not vendor.writes
    assert loaded_entry.recovery.history == before_history
    assert loaded_entry.recovery.failures == before_failures
    assert loaded_entry._store._data is None


async def test_pinned_working_host_reports_local_despite_stale_cloud_setting(
    hass, loaded_entry, vendor, freezer, http
):
    loaded_entry._auto_recovery = True
    loaded_entry._host_override = "192.0.2.10"
    loaded_entry._host_device_id = "hub"
    vendor.devices[0]["hub"]["tcpEnabled"] = False
    http.requests.clear()
    freezer.tick(timedelta(minutes=2))
    await loaded_entry.async_refresh()
    assert any(
        method == "GET"
        and url.host == "192.0.2.10"
        and url.path == "/device-state/currently-playing"
        for method, url in http.requests
    )
    assert loaded_entry.device_info_raw("hub")["hub"]["tcpEnabled"] is False
    assert loaded_entry.control_transport("hub") == "local"
    assert recovery_attributes(hass)["recovery_status"] == "local_available"
    assert not vendor.writes


async def test_cancelled_rearm_waits_for_executor_commit_without_rolling_back(
    hass, loaded_entry, vendor, freezer, monkeypatch, tmp_path
):
    await loaded_entry.async_soft_reboot("hub")
    await failed_probe(loaded_entry, vendor, freezer, 420)
    last_attempt = loaded_entry.recovery.history["hub"]["last_attempt"]
    started = asyncio.Event()
    release = threading.Event()
    storage_path = tmp_path / "gemstone-storage.json"
    fixture_write = Store._async_write_data
    original_write_prepared = Store._write_prepared_data

    async def real_subject_write(store, data):
        if store is loaded_entry._store:
            await _REAL_STORE_WRITE(store, data)
        else:
            await fixture_write(store, data)

    def delayed_write_prepared(store, mode, json_data):
        if store is loaded_entry._store:
            hass.loop.call_soon_threadsafe(started.set)
            if not release.wait(timeout=5):
                raise AssertionError("Test did not release the filesystem write")
        original_write_prepared(store, mode, json_data)

    with monkeypatch.context() as patcher:
        patcher.setattr(loaded_entry._store, "path", str(storage_path))
        patcher.setattr(Store, "_async_write_data", real_subject_write)
        patcher.setattr(Store, "_write_prepared_data", delayed_write_prepared)
        action_task = asyncio.create_task(loaded_entry.async_rearm_recovery("hub"))
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            action_task.cancel()
            await asyncio.sleep(0)
            assert not action_task.done()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await action_task

    # The cancelled caller cannot roll RAM back after its executor commits the
    # explicit re-arm, which would disagree with what HA loads next time.
    persisted = json.loads(await hass.async_add_executor_job(storage_path.read_bytes))
    assert persisted["data"]["recovery"]["hub"] == {
        "last_attempt": last_attempt,
        "attempted_outage": False,
    }
    assert loaded_entry.recovery.history["hub"] == persisted["data"]["recovery"]["hub"]
    assert len(reboots(vendor)) == 1


async def test_concurrent_saves_report_each_snapshots_own_write_result(
    hass, hass_storage, monkeypatch, tmp_path
):
    store = GemstoneStore(hass, 1, "gemstone_lights.concurrency", atomic_writes=True)
    storage_path = tmp_path / "gemstone-concurrent.json"
    started = asyncio.Event()
    release = threading.Event()
    committed = []
    fixture_write = Store._async_write_data
    original_write_prepared = Store._write_prepared_data

    async def real_subject_write(target, data):
        if target is store:
            await _REAL_STORE_WRITE(target, data)
        else:
            await fixture_write(target, data)

    def controlled_write(target, mode, json_data):
        marker = json.loads(json_data)["data"]["marker"]
        if marker == "A":
            hass.loop.call_soon_threadsafe(started.set)
            if not release.wait(timeout=5):
                raise AssertionError("Test did not release the first write")
        elif marker == "B":
            raise WriteError("Disk full for B")
        original_write_prepared(target, mode, json_data)
        committed.append(marker)

    with monkeypatch.context() as patcher:
        patcher.setattr(store, "path", str(storage_path))
        patcher.setattr(Store, "_async_write_data", real_subject_write)
        patcher.setattr(Store, "_write_prepared_data", controlled_write)
        saves = [asyncio.create_task(store.async_save({"marker": "A"}))]
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            saves.extend(
                asyncio.create_task(store.async_save({"marker": marker}))
                for marker in ("B", "C")
            )
            # Let both callers and their owned write tasks reach Store while
            # A's executor is held, exposing any shared pending-data overwrite.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        finally:
            release.set()
            results = await asyncio.gather(*saves, return_exceptions=True)

    assert results[0] is None
    assert isinstance(results[1], OSError)
    assert results[2] is None
    assert committed == ["A", "C"]
    persisted = json.loads(await hass.async_add_executor_job(storage_path.read_bytes))
    assert persisted["data"] == {"marker": "C"}


async def test_failed_rearm_cannot_leak_into_concurrent_catalog_save(
    hass, loaded_entry, vendor, freezer, monkeypatch, tmp_path
):
    await loaded_entry.async_soft_reboot("hub")
    await failed_probe(loaded_entry, vendor, freezer, 2)
    before_history = deepcopy(loaded_entry.recovery.history)
    before_failures = deepcopy(loaded_entry.recovery.failures)
    storage_path = tmp_path / "gemstone-recovery-and-catalog.json"
    started = asyncio.Event()
    release = threading.Event()
    fixture_write = Store._async_write_data
    original_write_prepared = Store._write_prepared_data
    writes = []

    async def real_subject_write(store, data):
        if store is loaded_entry._store:
            await _REAL_STORE_WRITE(store, data)
        else:
            await fixture_write(store, data)

    def fail_first_write(store, mode, json_data):
        writes.append(json.loads(json_data))
        if len(writes) == 1:
            hass.loop.call_soon_threadsafe(started.set)
            if not release.wait(timeout=5):
                raise AssertionError("Test did not release the failed re-arm write")
            raise WriteError("Disk full during re-arm")
        original_write_prepared(store, mode, json_data)

    with monkeypatch.context() as patcher:
        patcher.setattr(loaded_entry._store, "path", str(storage_path))
        patcher.setattr(Store, "_async_write_data", real_subject_write)
        patcher.setattr(Store, "_write_prepared_data", fail_first_write)
        tasks = [asyncio.create_task(loaded_entry.async_rearm_recovery("hub"))]
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            tasks.append(
                asyncio.create_task(
                    loaded_entry.catalog.save(
                        "hub", "pattern", "Concurrent pattern", {"colors": [65280]}
                    )
                )
            )
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        finally:
            release.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)

    assert isinstance(results[0], HomeAssistantError)
    assert "recovery limits unchanged" in str(results[0])
    assert results[1] is None
    assert loaded_entry.recovery.history == before_history
    assert loaded_entry.recovery.failures == before_failures
    persisted = json.loads(await hass.async_add_executor_job(storage_path.read_bytes))
    assert persisted["data"]["recovery"] == before_history
    assert (
        persisted["data"]["local_catalog"]["patterns"][0]["name"]
        == "Concurrent pattern"
    )
    assert len(reboots(vendor)) == 1
