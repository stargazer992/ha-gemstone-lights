"""What each controller animation reads from a pattern.

Animations do not share one pattern shape. Some take no ``direction`` and
some only a few of the six; some draw a ``backgroundColor`` and the rest
ignore it; and twelve read numbered ``extraParameters``, which the firmware
otherwise fills with whatever it last held. Effects chosen in Home Assistant
are built from this table so each animation receives what it expects.

Facts taken from Gemstone's animation specification as published in
GemstoneLights/home_assistant_gemstone_lights. Note that ``motionless``
defines only extra parameter 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

# 0 Right, 1 Left, 2 Right & Left, 3 In, 4 Out, 5 In & Out
ALL_DIRECTIONS: Final = (0, 1, 2, 3, 4, 5)


@dataclass(frozen=True)
class Extra:
    """One numbered extra parameter and its default."""

    index: int
    name: str
    default: int


@dataclass(frozen=True)
class AnimationSpec:
    """The pattern fields one animation reads."""

    background: bool
    directions: tuple[int, ...] = ()
    extras: tuple[Extra, ...] = ()


ANIMATION_SPECS: Final[dict[str, AnimationSpec]] = {
    "accent": AnimationSpec(
        False, (), (Extra(0, "On Length", 1), Extra(1, "Off Length", 5))
    ),
    "around": AnimationSpec(False, (0, 1, 2)),
    "chase": AnimationSpec(False, ALL_DIRECTIONS),
    "eyeball": AnimationSpec(
        True,
        (),
        (
            Extra(0, "Eye White Color", 16777215),
            Extra(1, "Eye White Size", 20),
            Extra(2, "Iris Size", 6),
            Extra(3, "Pupil Color", 0),
            Extra(4, "Pupil Size", 4),
            Extra(5, "Spacing", 5),
        ),
    ),
    "fade": AnimationSpec(False),
    "fireworks": AnimationSpec(
        True,
        (),
        (
            Extra(0, "Firework Count", 4),
            Extra(1, "Rocket Color", 4278190080),
            Extra(2, "Rocket Travel %", 25),
        ),
    ),
    "flicker": AnimationSpec(True),
    "flow": AnimationSpec(True, (0, 1, 2, 3, 4)),
    "ghost": AnimationSpec(True, (0, 1, 2)),
    "glitch": AnimationSpec(True),
    "glitter": AnimationSpec(
        True, (), (Extra(0, "Reverse Fade", 0), Extra(1, "Active Light %", 60))
    ),
    "gradient": AnimationSpec(False, (0, 1, 2)),
    "gradient_wave": AnimationSpec(False, (0, 1, 3, 4), (Extra(0, "Length", 20),)),
    "isofade": AnimationSpec(
        True, (), (Extra(0, "On Length", 1), Extra(1, "Off Length", 3))
    ),
    "marquee": AnimationSpec(False, ALL_DIRECTIONS),
    "motionless": AnimationSpec(True, (), (Extra(1, "Length", 1),)),
    "multipulse": AnimationSpec(True, (0, 1, 2, 3)),
    "pacman": AnimationSpec(False, (0, 1, 3, 4, 5)),
    "pulse": AnimationSpec(False, (0, 1)),
    "pyramid_chase": AnimationSpec(
        False,
        ALL_DIRECTIONS,
        (
            Extra(0, "Pyramid Length", 20),
            Extra(1, "Color Length", 40),
            Extra(2, "Pyramid Base Brightness", 25),
        ),
    ),
    "smooth": AnimationSpec(
        True, ALL_DIRECTIONS, (Extra(0, "Color Length", 10), Extra(1, "Spacing", 2))
    ),
    "spectrum": AnimationSpec(
        False,
        (),
        (
            Extra(0, "Gradient Length", 10),
            Extra(1, "Solid Length", 0),
            Extra(2, "Gradient Mode", 1),
        ),
    ),
    "spotlight": AnimationSpec(True),
    "stack": AnimationSpec(True, (0, 1, 2)),
    "starry": AnimationSpec(True),
    "stretch": AnimationSpec(False, (0, 1, 2)),
    "sway": AnimationSpec(False, ALL_DIRECTIONS),
    "tremor": AnimationSpec(True, (), (Extra(0, "Intensity %", 70),)),
    "wave": AnimationSpec(
        False, (0, 1, 3, 4), (Extra(0, "Length", 20), Extra(1, "Tail Brightness", 70))
    ),
}


def apply_animation(pattern: dict[str, Any], animation: str) -> dict[str, Any]:
    """Set ``animation`` on a pattern and give it the fields that animation reads.

    A direction the animation allows is kept, otherwise its first one is used;
    fields the animation does not read are removed. Unknown animations (newer
    firmware) keep the pattern's existing fields.
    """
    pattern["animation"] = animation
    spec = ANIMATION_SPECS.get(animation)
    if spec is None:
        return pattern
    if spec.directions:
        if pattern.get("direction") not in spec.directions:
            pattern["direction"] = spec.directions[0]
    else:
        pattern.pop("direction", None)
    if spec.background:
        pattern.setdefault("backgroundColor", 0)
    else:
        pattern.pop("backgroundColor", None)
    if spec.extras:
        pattern["extraParameters"] = {
            "version": 0,
            **{
                str(extra.index): {"value": extra.default, "name": extra.name}
                for extra in spec.extras
            },
        }
    else:
        pattern.pop("extraParameters", None)
    return pattern
