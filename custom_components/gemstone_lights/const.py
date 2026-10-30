"""Constants for the Gemstone Lights integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "gemstone_lights"

# --- Gemstone cloud (AWS), used only for the one-time account import --------
# These identifiers are embedded in the official Gemstone Lights mobile app.
AWS_REGION: Final = "us-west-2"
COGNITO_USER_POOL_ID: Final = "us-west-2_rr5lY7Etr"
COGNITO_CLIENT_ID: Final = "2647t144niotrl53vvru0ivno7"
API_BASE_URL: Final = "https://mytpybpq12.execute-api.us-west-2.amazonaws.com/prod"

# The API rejects requests that do not look like the mobile app. If imports
# start failing with HTTP 4xx, update these to the current app release.
APP_HEADERS: Final = {
    "app-environment": "Production",
    "app-platform": "Android",
    "app-version": "0.6.64",
    "app-build-number": "664",
    "app-device-type": "phone",
    "content-type": "application/json",
}

# --- Integration -----------------------------------------------------------
CONF_BLUETOOTH_ADDRESS: Final = "bluetooth_address"
CONF_LOCAL_ONLY: Final = "local_only"
CONF_LOCAL_DEVICE: Final = "local_device"
CONF_EMAIL: Final = "email"
CONF_PASSWORD: Final = "password"
# Account content handed from the config flow to the first setup, then removed.
CONF_IMPORT: Final = "import"

DEFAULT_SCAN_INTERVAL: Final = timedelta(seconds=30)

REQUEST_TIMEOUT: Final = 30

MANUFACTURER: Final = "Gemstone Lights"

# Keys used inside the coordinator data structure.
DATA_DEVICES: Final = "devices"
DATA_INFO: Final = "info"
DATA_STATE: Final = "state"
DATA_DESIGNS: Final = "designs"
DATA_PATTERNS: Final = "patterns"

# Shown in a select when nothing recognisable is playing.
OPTION_NONE: Final = "None"

# Shown in the library folder select before a folder is chosen.
OPTION_PICK_FOLDER: Final = "Pick a folder"


# --- Effects ---------------------------------------------------------------
# Animation identifiers understood by the controller. These ship with the
# official app; "motionless" simply holds the colours still.
ANIMATIONS: Final = [
    "accent",
    "around",
    "chase",
    "eyeball",
    "fade",
    "fireworks",
    "flicker",
    "flow",
    "ghost",
    "glitch",
    "glitter",
    "gradient",
    "gradient_wave",
    "isofade",
    "marquee",
    "motionless",
    "multipulse",
    "pacman",
    "pulse",
    "pyramid_chase",
    "smooth",
    "spectrum",
    "spotlight",
    "stack",
    "starry",
    "stretch",
    "sway",
    "tremor",
    "wave",
]

# Presented instead of an animation when showing one plain colour.
EFFECT_SOLID: Final = "Solid"
EFFECT_LIST: Final = [EFFECT_SOLID, *ANIMATIONS]

DEFAULT_SPEED: Final = 128
DATA_ZONES: Final = "zones"

# --- Local control ---------------------------------------------------------
# The Hub2 serves an unauthenticated HTTP API on port 80 when "Allow Local
# Commands" is enabled in the Gemstone app.
CONF_HOST: Final = "host"
CONF_HOST_DEVICE: Final = "host_device_id"
CONF_ENABLE_LOCAL: Final = "enable_local"
LOCAL_TIMEOUT: Final = 8
LOCAL_MAX_PAYLOAD: Final = 15 * 1024
# The vendor drivers tag their writes; the controller echoes this back.
LOCAL_ORIGIN: Final = "control4"
# The controller ignores writes that arrive back to back.
LOCAL_WRITE_GAP: Final = 1.5
DATA_LOCAL: Final = "local"
DATA_SETTINGS: Final = "settings"
