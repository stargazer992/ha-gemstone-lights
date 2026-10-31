"""The one-time account import through Home Assistant's real config flow."""

import pytest
from botocore.exceptions import ClientError

WARM = {"id": "warm-ww", "name": "Glamo WW", "colors": [255], "animation": "motionless"}
HOLIDAY = {"id": "xmas-ww", "name": "Glamo WW", "colors": [65280], "animation": "chase"}


@pytest.fixture
def account(vendor):
    """An account with two folders sharing a pattern name, and a library."""
    vendor.zones["hub"][0]["pixelCount"] = 3
    vendor.devices[0]["hub"].update(pixelCount=300, rgbwSequence="GRBW")
    vendor.folders = [
        {"folderId": "warm", "name": "Warm"},
        {"folderId": "holiday", "name": "Holiday"},
    ]
    vendor.patterns = {
        "warm": [
            {"id": "fav-1", "folderId": "warm", "patternData": WARM, "isFavorite": True}
        ],
        "holiday": [
            {"patternData": HOLIDAY},
            {
                "id": "fav-1",
                "folderId": "warm",
                "patternData": WARM,
                "isFavorite": True,
            },
        ],
    }
    vendor.library_folders = [
        {"id": "lib", "folderName": "Christmas", "category": "holidays"}
    ]
    vendor.library_patterns = [
        {
            "downloadableFolderId": "lib",
            "patternName": "Candy Cane",
            "patternData": {
                "name": "Candy Cane",
                "colors": [255, 4294967040],
                "animation": "chase",
            },
        }
    ]
    return vendor


async def start_import(hass, **fields):
    return await hass.config_entries.flow.async_init(
        "gemstone_lights",
        context={"source": "user"},
        data={"email": "test@example.invalid", "password": "test-password", **fields},
    )


async def test_import_keeps_setup_and_favorites_then_never_uses_cloud(
    hass, account, http, config_dir, cognito_external, enable_custom_integrations
):
    # Given an account controller reachable on the LAN.
    # When it is imported once and the integration then polls normally.
    result = await start_import(hass)
    await hass.async_block_till_done()
    entry = result["result"]
    coordinator = entry.runtime_data
    http.requests.clear()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    # Then credentials are not kept, the hand-off payload is consumed, and only LAN is used.
    assert entry.unique_id == "hub"
    assert "password" not in entry.data and "email" not in entry.data
    assert "import" not in entry.data
    assert entry.data["local_device"]["hub"]["pixelCount"] == 300
    assert {zone["id"] for zone in coordinator.zones("hub")} == {"front", "back"}
    assert sorted(p["data"]["id"] for p in coordinator.patterns()) == [
        "warm-ww",
        "xmas-ww",
    ]
    assert coordinator.find_library_pattern("Candy Cane")["animation"] == "chase"
    pattern_select = next(
        state
        for state in hass.states.async_all("select")
        if "Glamo WW (Warm)" in state.attributes.get("options", [])
    )
    assert pattern_select.attributes["favorites"] == ["Glamo WW (Warm)"]
    assert (config_dir / "www" / "gemstones" / "index.json").exists()
    assert {url.host for _, url in http.requests} == {"192.0.2.10"}
    await hass.config_entries.async_unload(entry.entry_id)


async def test_unreachable_imported_address_asks_for_one(
    hass, account, cognito_external, enable_custom_integrations
):
    # Given the controller does not answer at the address the account reports.
    account.failures["/device-state/hub-settings"] = 503
    result = await start_import(hass)
    assert result["step_id"] == "import_host"
    # When the user enters the address once the controller answers again.
    account.failures.clear()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.0.2.10"}
    )
    await hass.async_block_till_done()
    # Then the entry is created for that address.
    assert result["type"] == "create_entry"
    assert result["data"]["host"] == "192.0.2.10"
    await hass.config_entries.async_unload(result["result"].entry_id)


@pytest.mark.parametrize("consent", [False, True])
async def test_local_commands_are_switched_on_only_with_consent(
    hass, account, cognito_external, enable_custom_integrations, consent
):
    # Given the controller's Allow Local Commands setting is off.
    account.devices[0]["hub"]["tcpEnabled"] = False
    # When the import is submitted with or without permission to change it.
    result = await start_import(hass, enable_local=consent)
    await hass.async_block_till_done()
    # Then the controller setting is written only when permitted.
    writes = [w for w in account.writes if w[2] == "/deviceControl/deviceSettings"]
    assert writes == (
        [("cloud", "hub", "/deviceControl/deviceSettings", {"tcpEnabled": True})]
        if consent
        else []
    )
    await hass.config_entries.async_unload(result["result"].entry_id)


async def test_refused_app_identity_reports_actionable_error(
    hass, account, cognito_external, enable_custom_integrations
):
    # Given the cloud refuses the app version this integration presents.
    account.failures["/homegroup/list"] = 426
    # When the import is submitted.
    result = await start_import(hass)
    # Then setup explains the refusal and creates nothing.
    assert result["errors"] == {"base": "cloud_rejected"}
    assert hass.config_entries.async_entries("gemstone_lights") == []


async def test_bad_credentials_return_an_actionable_setup_error(
    hass, account, cognito_external, monkeypatch, enable_custom_integrations
):
    # Given Cognito rejects the account's credentials at the external SDK boundary.
    def reject(user, password):
        raise ClientError({"Error": {"Code": "NotAuthorizedException"}}, "InitiateAuth")

    monkeypatch.setattr("pycognito.Cognito.authenticate", reject)
    # When the user submits the import form.
    result = await start_import(hass)
    # Then setup stays on the form with an authentication error.
    assert result["errors"] == {"base": "invalid_auth"}
    assert hass.config_entries.async_entries("gemstone_lights") == []


async def test_already_imported_controller_is_not_offered_again(
    hass, entry, account, cognito_external, enable_custom_integrations
):
    # Given the account's only controller is already configured.
    # When the import runs again.
    result = await start_import(hass)
    # Then it aborts instead of creating a duplicate.
    assert result["reason"] == "no_new_controllers"
