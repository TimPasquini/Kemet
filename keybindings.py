"""
keybindings.py - Centralized key mappings for Kemet (Pygame version)

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


# Number keys for toolbar selection (1-9) - selects tool without using it
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

# Primary action keys
USE_TOOL_KEY = _key("f")      # Use currently selected tool
INTERACT_KEY = _key("e")      # Collect water / resupply at depot / interact with structure
TOOL_MENU_KEY = _key("r")     # Open tool submenu (for tools with options)
REST_KEY = _key("SPACE")      # Rest at night to end day

# Menu navigation (when tool menu is open)
MENU_UP_KEY = _key("w")
MENU_DOWN_KEY = _key("s")
MENU_SELECT_KEY = _key("f")   # Same as use tool
MENU_CANCEL_KEY = _key("r")   # Toggle off

# System keys
QUIT_KEY = _key("ESCAPE")
HELP_KEY = _key("h")

# Control descriptions for help display
CONTROL_DESCRIPTIONS = [
    "WASD: move",
    "1-9: select tool",
    "F: use tool",
    "R: options menu",
    "W/S: menu nav",
    "E: interact",
    "Space: rest",
    "H: help",
    "Esc: quit/cancel",
    "LClick: select",
    "RClick: options",
    "Scroll: zoom / log",
    "+/-: zoom",
]
