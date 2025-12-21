# water.py
"""
water.py - Water data model for Kemet

Defines the WaterColumn data structure for subsurface water storage.
Simulation logic has been moved to simulation/subsurface.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

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
    # Fixed size list for layers defined in SoilLayer
    _levels: List[int] = field(default_factory=lambda: [0] * len(SoilLayer))
    # Cache total for O(1) access
    _total: int = 0

    def get_layer_water(self, layer: SoilLayer) -> int:
        """Get water amount in a specific layer."""
        return self._levels[layer]

    def set_layer_water(self, layer: SoilLayer, amount: int) -> None:
        """Set water amount in a specific layer, ensuring it's not negative."""
        amount = max(0, amount)
        diff = amount - self._levels[layer]
        self._levels[layer] = amount
        self._total += diff

    def add_layer_water(self, layer: SoilLayer, amount: int) -> None:
        """Add water to a specific layer."""
        if amount <= 0:
            return
        self._levels[layer] += amount
        self._total += amount

    def remove_layer_water(self, layer: SoilLayer, amount: int) -> int:
        """
        Remove water from a layer.

        Returns actual amount removed (could be less if insufficient water).
        """
        current = self._levels[layer]
        actual = min(amount, current)
        self._levels[layer] -= actual
        self._total -= actual
        return actual

    def total_subsurface_water(self) -> int:
        """Total water in all subsurface layers."""
        return self._total
