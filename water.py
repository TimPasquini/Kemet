# water.py
"""
water.py - Water data model for Kemet

Defines the WaterColumn data structure for subsurface water storage.
Simulation logic has been moved to simulation/subsurface.py.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Tuple

from ground import SoilLayer

Point = Tuple[int, int]


@dataclass
class WaterColumn:
    """
    Water storage for a tile's subsurface soil layers.

    Each layer stores water as integer units (1 unit = 100mm).
    Water fills based on layer porosity and material properties.

    Note: Surface water is stored per-SubSquare in subgrid.py, not here.
    """
    layer_water: Dict[SoilLayer, int] = field(
        default_factory=lambda: defaultdict(int)
    )

    def get_layer_water(self, layer: SoilLayer) -> int:
        """Get water amount in a specific layer."""
        return self.layer_water[layer]

    def set_layer_water(self, layer: SoilLayer, amount: int) -> None:
        """Set water amount in a specific layer, ensuring it's not negative."""
        self.layer_water[layer] = max(0, amount)

    def add_layer_water(self, layer: SoilLayer, amount: int) -> None:
        """Add water to a specific layer."""
        self.layer_water[layer] += amount

    def remove_layer_water(self, layer: SoilLayer, amount: int) -> int:
        """
        Remove water from a layer.

        Returns actual amount removed (could be less if insufficient water).
        """
        current = self.get_layer_water(layer)
        actual = min(amount, current)
        self.set_layer_water(layer, current - actual)
        return actual

    def total_subsurface_water(self) -> int:
        """Total water in all subsurface layers."""
        return sum(self.layer_water.values())
