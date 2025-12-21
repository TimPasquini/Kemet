# tools.py
"""
tools.py - Tool system for Kemet

Stardew Valley / Zelda-style tool system:
- Tools are items in inventory assigned to hotbar slots
- Select with 1-9, use with F
- Some tools have submenus (R to open when selected)
- Tools can interact with ground, water, and structures

Future: tool levels, durability, efficiency scaling
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Dict


class ToolCategory(Enum):
    """Tool categories for organization and behavior."""
    TERRAIN = auto()      # Modifies ground/elevation
    WATER = auto()        # Interacts with water
    BUILD = auto()        # Places structures (has submenu)
    UTILITY = auto()      # Information/misc tools


@dataclass
class ToolOption:
    """A submenu option for tools that have multiple modes."""
    id: str
    name: str
    description: str
    cost: Dict[str, int] = field(default_factory=dict)  # Resource costs
    icon: str = "?"
    action_args: List[str] = field(default_factory=list) # Extra args for the action


@dataclass
class Tool:
    """
    Represents a tool in the player's inventory/hotbar.

    Tools can:
    - Have a primary action (F key)
    - Have a submenu of options (R key) for tools like Build
    - Apply effects to terrain, water, or structures
    - Scale effects based on level (future)
    """
    id: str                      # Unique identifier
    name: str                    # Display name
    description: str             # Help text
    category: ToolCategory       # For grouping/behavior
    icon: str = "?"              # Single char for toolbar

    # Submenu options (for tools like Build)
    options: List[ToolOption] = field(default_factory=list)
    selected_option: int = 0     # Currently selected submenu option

    # Action mapping (what command to issue)
    action: str = ""             # Base command name
    action_args: List[str] = field(default_factory=list)

    def has_menu(self) -> bool:
        """Returns True if this tool has a submenu."""
        return len(self.options) > 0

    def get_current_option(self) -> Optional[ToolOption]:
        """Get the currently selected submenu option."""
        if self.options and 0 <= self.selected_option < len(self.options):
            return self.options[self.selected_option]
        return None

    def cycle_option(self, direction: int = 1) -> None:
        """Cycle through submenu options."""
        if self.options:
            self.selected_option = (self.selected_option + direction) % len(self.options)

    def get_action(self) -> tuple[str, List[str]]:
        """Get the action and args to execute for this tool."""
        if self.options:
            opt = self.get_current_option()
            if opt:
                return self.action, [opt.id] + opt.action_args
        return self.action, self.action_args


# =============================================================================
# Tool Definitions
# =============================================================================

TOOL_SHOVEL = Tool(
    id="shovel",
    name="Shovel",
    description="Dig trenches or modify terrain elevation",
    category=ToolCategory.TERRAIN,
    icon="⌁",
    options=[
        ToolOption("trench", "Dig Trench", "Reduces evaporation, improves flow", action_args=["topsoil"]),
        ToolOption("lower", "Lower Ground", "Remove topsoil/organics", action_args=["topsoil"]),
        ToolOption("raise", "Raise Ground", "Add topsoil (1 scrap)", cost={"scrap": 1}, action_args=["topsoil"]),
    ],
    action="terrain",  # Will dispatch based on selected option
)

TOOL_PICKAXE = Tool(
    id="pickaxe",
    name="Pickaxe",
    description="Break hard rock and compact soil",
    category=ToolCategory.TERRAIN,
    icon="⛏",
    options=[
        ToolOption("trench", "Dig Trench", "Dig trench in hard ground", action_args=["regolith"]),
        ToolOption("lower", "Break Ground", "Dig regolith/subsoil", action_args=["regolith"]),
        ToolOption("raise", "Pile Gravel", "Add gravel/regolith (1 scrap)", cost={"scrap": 1}, action_args=["regolith"]),
    ],
    action="terrain",
)

TOOL_BUCKET = Tool(
    id="bucket",
    name="Bucket",
    description="Carry and pour water",
    category=ToolCategory.WATER,
    icon="▾",
    action="pour",
    action_args=["1"],
)

TOOL_BUILD = Tool(
    id="build",
    name="Build",
    description="Construct structures",
    category=ToolCategory.BUILD,
    icon="⌂",
    options=[
        ToolOption("cistern", "Cistern", "Store water (3 scrap)", cost={"scrap": 3}),
        ToolOption("condenser", "Condenser", "Generate water (2 scrap)", cost={"scrap": 2}),
        ToolOption("planter", "Planter", "Grow biomass (1 scrap, 1 seed)", cost={"scrap": 1, "seeds": 1}),
    ],
    action="build",
)

TOOL_SURVEY = Tool(
    id="survey",
    name="Survey",
    description="Examine tile details",
    category=ToolCategory.UTILITY,
    icon="?",
    action="survey",
)


# Default toolbar configuration
DEFAULT_TOOLS: List[Tool] = [
    TOOL_SHOVEL,
    TOOL_PICKAXE,
    TOOL_BUCKET,
    TOOL_BUILD,
    TOOL_SURVEY,
]


class Toolbar:
    """
    Manages the player's tool hotbar.

    Handles tool selection, menu state, and action dispatch.
    """

    def __init__(self, tools: Optional[List[Tool]] = None):
        self.tools = tools if tools is not None else list(DEFAULT_TOOLS)
        self.selected_index: int = 0
        self.menu_open: bool = False
        self.menu_highlight_index: int = 0  # Highlighted option in expanded menu

    def get_selected_tool(self) -> Optional[Tool]:
        """Get the currently selected tool."""
        if 0 <= self.selected_index < len(self.tools):
            return self.tools[self.selected_index]
        return None

    def select_tool(self, index: int) -> bool:
        """Select a tool by index (0-based). Returns True if valid."""
        if 0 <= index < len(self.tools):
            # Close menu when switching tools
            if self.selected_index != index:
                self.menu_open = False
            self.selected_index = index
            return True
        return False

    def select_by_number(self, num: int) -> bool:
        """Select tool by number key (1-based). Returns True if valid."""
        return self.select_tool(num - 1)

    def open_menu(self) -> bool:
        """Open the tool's submenu. Returns True if menu opened."""
        tool = self.get_selected_tool()
        if tool and tool.has_menu():
            self.menu_open = True
            self.menu_highlight_index = tool.selected_option
            return True
        return False

    def toggle_menu(self) -> bool:
        """Toggle the tool's submenu. Returns True if menu is now open."""
        tool = self.get_selected_tool()
        if tool and tool.has_menu():
            if self.menu_open:
                self.menu_open = False
            else:
                self.open_menu()
            return self.menu_open
        return False

    def cycle_menu_highlight(self, direction: int = 1) -> None:
        """Move the highlight up or down in the expanded menu."""
        if self.menu_open:
            tool = self.get_selected_tool()
            if tool and tool.options:
                self.menu_highlight_index = (self.menu_highlight_index + direction) % len(tool.options)

    def confirm_menu_selection(self) -> None:
        """Confirm the highlighted option and close the menu."""
        if self.menu_open:
            tool = self.get_selected_tool()
            if tool:
                tool.selected_option = self.menu_highlight_index
            self.menu_open = False

    def cycle_menu_option(self, direction: int = 1) -> None:
        """Cycle through menu options if menu is open."""
        if self.menu_open:
            tool = self.get_selected_tool()
            if tool:
                tool.cycle_option(direction)

    def close_menu(self) -> None:
        """Close the submenu."""
        self.menu_open = False

    def get_tool_count(self) -> int:
        """Get number of tools in toolbar."""
        return len(self.tools)


# =============================================================================
# Compatibility functions (for gradual migration)
# =============================================================================

# Global toolbar instance for simple access
_toolbar = Toolbar()

def get_toolbar() -> Toolbar:
    """Get the global toolbar instance."""
    return _toolbar

def get_tool_by_number(num: int) -> Optional[Tool]:
    """Get tool by number key (1-9). Returns None if invalid."""
    if 1 <= num <= len(_toolbar.tools):
        return _toolbar.tools[num - 1]
    return None

def get_tool_count() -> int:
    """Get total number of tools."""
    return _toolbar.get_tool_count()

# For backwards compatibility with render code
TOOLS = _toolbar.tools