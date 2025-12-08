"""
keybindings.py - Centralized key mappings for Kemet

Single source of truth for all keyboard controls.
"""
from __future__ import annotations

try:
    import pygame
except ImportError:
    # Allow import without pygame for type checking
    pygame = None


def _key(name: str) -> int:
    """Get pygame key constant by name, or placeholder if pygame not loaded."""
    if pygame is None:
        return 0
    return getattr(pygame, f"K_{name}", 0)


# Movement keys (continuous hold) - maps to (dx, dy)
MOVE_KEYS = {
    _key("w"): (0, -1),
    _key("a"): (-1, 0),
    _key("s"): (0, 1),
    _key("d"): (1, 0),
}

# Action keys (single press) - maps to (command, args)
ACTION_KEYS = {
    _key("t"): ("dig", []),
    _key("z"): ("lower", []),
    _key("x"): ("raise", []),
    _key("c"): ("build", ["cistern"]),
    _key("n"): ("build", ["condenser"]),
    _key("p"): ("build", ["planter"]),
    _key("e"): ("collect", []),
    _key("f"): ("pour", ["1"]),
    _key("v"): ("survey", []),
    _key("SPACE"): ("end", []),
}

# Number keys for toolbar selection (1-9)
TOOL_KEYS = {
    _key("1"): 1,
    _key("2"): 2,
    _key("3"): 3,
    _key("4"): 4,
    _key("5"): 5,
    _key("6"): 6,
    _key("7"): 7,
    _key("8"): 8,
    _key("9"): 9,
}

# System keys
QUIT_KEY = _key("ESCAPE")
HELP_KEY = _key("h")

# Control descriptions for help display
CONTROL_DESCRIPTIONS = [
    "WASD: move",
    "1: dig trench",
    "2: lower ground",
    "3: raise ground",
    "4: cistern",
    "5: condenser",
    "6: planter",
    "7: collect",
    "8: pour 1L",
    "9: survey",
    "Space: rest",
    "H: help",
    "Esc: quit",
]
