# world_state.py
"""Global world state tracking for conservation of mass/water.

These systems track resources across the entire world, enabling:
- Water conservation: edge runoff returns to wellspring pool
- Sediment tracking: eroded material can return via dust storms
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GlobalWaterPool:
    """Conservation of water across the world.

    Water flows in a closed cycle:
    - Wellsprings draw from total_volume
    - Edge runoff adds to total_volume
    - Evaporation moves water to atmospheric_reserve
    - Rain draws from atmospheric_reserve

    This ensures water is never created or destroyed during gameplay.
    """
    total_volume: int = 0           # Total water in the underground/aquifer system
    atmospheric_reserve: int = 0    # Water evaporated into "sky" (returns via rain)

    def wellspring_draw(self, amount: int) -> int:
        """Wellsprings draw from finite pool.

        Args:
            amount: Desired water output

        Returns:
            Actual amount drawn (may be less if pool is depleted)
        """
        actual = min(amount, self.total_volume)
        self.total_volume -= actual
        return actual

    def edge_runoff(self, amount: int) -> None:
        """Water flowing off map returns to pool (aquifer recharge)."""
        self.total_volume += amount

    def evaporate(self, amount: int) -> None:
        """Water evaporates to atmosphere."""
        self.atmospheric_reserve += amount

    def rain(self, amount: int) -> int:
        """Rain draws from atmospheric reserve.

        Args:
            amount: Desired rainfall amount

        Returns:
            Actual amount available (may be less if atmosphere is dry)
        """
        actual = min(amount, self.atmospheric_reserve)
        self.atmospheric_reserve -= actual
        return actual

    def get_total_water(self) -> int:
        """Total water in the system (underground + atmosphere)."""
        return self.total_volume + self.atmospheric_reserve


@dataclass
class SedimentPool:
    """Tracks material that has eroded off map edges.

    Material lost to edges can return via dust storms,
    ensuring conservation of mass over time.
    """
    accumulated: int = 0    # Total sediment waiting to return

    def add_sediment(self, amount: int) -> None:
        """Add eroded material to the pool."""
        self.accumulated += amount

    def take_for_storm(self, max_amount: int) -> int:
        """Take sediment for a dust storm.

        Args:
            max_amount: Maximum amount the storm can carry

        Returns:
            Actual amount taken
        """
        actual = min(max_amount, self.accumulated)
        self.accumulated -= actual
        return actual
