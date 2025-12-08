"""
tools.py - Tool definitions for Kemet toolbar

Defines the toolbar tools available to the player.
Tools are selected by number keys and activated by action key.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Tool:
    """Represents a tool in the toolbar."""
    name: str
    description: str
    action: str              # Command name to issue
    args: List[str] = field(default_factory=list)
    icon: str = "?"          # Single char for toolbar display


# Toolbar tools in order (index + 1 = number key)
TOOLS: List[Tool] = [
    Tool(
        name="Trench",
        description="Dig trench to reduce evaporation",
        action="dig",
        icon="=",
    ),
    Tool(
        name="Lower",
        description="Remove topsoil to lower elevation",
        action="lower",
        icon="v",
    ),
    Tool(
        name="Raise",
        description="Add topsoil (1 scrap)",
        action="raise",
        icon="^",
    ),
    Tool(
        name="Cistern",
        description="Store water (3 scrap)",
        action="build",
        args=["cistern"],
        icon="C",
    ),
    Tool(
        name="Condenser",
        description="Generate water (2 scrap)",
        action="build",
        args=["condenser"],
        icon="N",
    ),
    Tool(
        name="Planter",
        description="Grow biomass (1 scrap, 1 seed)",
        action="build",
        args=["planter"],
        icon="P",
    ),
    Tool(
        name="Collect",
        description="Gather water or resupply at depot",
        action="collect",
        icon="E",
    ),
    Tool(
        name="Pour",
        description="Pour 1L water onto tile",
        action="pour",
        args=["1"],
        icon="~",
    ),
    Tool(
        name="Survey",
        description="Examine current tile details",
        action="survey",
        icon="?",
    ),
]


def get_tool_by_number(num: int) -> Optional[Tool]:
    """Get tool by number key (1-9). Returns None if invalid."""
    if 1 <= num <= len(TOOLS):
        return TOOLS[num - 1]
    return None


def get_tool_count() -> int:
    """Get total number of tools."""
    return len(TOOLS)
