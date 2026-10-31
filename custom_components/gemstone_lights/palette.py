"""The Gemstone app's colour swatches, for Home Assistant's colour picker.

The app shows each swatch in a screen colour but sends an LED-tuned value:
its orange and yellow look red and orange on a screen, and its three whites
use different LEDs (warm white the warm channel, cool white the RGB LEDs,
bright white all of them) yet look alike on a screen. Home Assistant shows
a favourite as the colour it sends, so the light entity translates at the
boundary: swatch colours go to the controller as the app's values, and the
app's values come back as swatch colours.
"""

from __future__ import annotations

from typing import Final

RGBW = tuple[int, int, int, int]

# (name, shown in Home Assistant, sent to the controller), in the app's order.
PALETTE: Final[tuple[tuple[str, RGBW, RGBW], ...]] = (
    ("Warm White", (253, 244, 188, 0), (0, 0, 0, 255)),
    ("Cool White", (244, 253, 255, 0), (255, 255, 255, 0)),
    ("Bright White", (255, 255, 255, 0), (255, 255, 255, 255)),
    ("Red", (255, 0, 0, 0), (255, 0, 0, 0)),
    ("Orange", (255, 165, 0, 0), (255, 30, 0, 0)),
    ("Yellow", (255, 255, 0, 0), (255, 87, 0, 0)),
    ("Green", (0, 255, 0, 0), (0, 255, 0, 0)),
    ("Aqua", (0, 217, 255, 0), (0, 217, 255, 0)),
    ("Blue", (0, 0, 255, 0), (0, 0, 255, 0)),
    ("Purple", (132, 0, 255, 0), (132, 0, 255, 0)),
    ("Pink", (255, 105, 180, 0), (255, 0, 122, 0)),
)

FAVORITE_COLORS: Final = [{"rgbw_color": list(shown)} for _, shown, _ in PALETTE]

_TO_CONTROLLER: Final = {shown: sent for _, shown, sent in PALETTE}
_TO_DISPLAY: Final = {sent: shown for _, shown, sent in PALETTE}


def to_controller(rgbw: RGBW) -> RGBW:
    """Return what to send for a colour picked in Home Assistant."""
    return _TO_CONTROLLER.get(tuple(rgbw), tuple(rgbw))


def to_display(rgbw: RGBW | None) -> RGBW | None:
    """Return the colour to show for one the controller reported."""
    if rgbw is None:
        return None
    return _TO_DISPLAY.get(tuple(rgbw), tuple(rgbw))
