# water.py
"""
water.py - Water simulation system for Kemet

Implements water storage and movement through fixed soil layers:
- Surface water (fast flow, high evaporation)
- Subsurface water in each soil layer (slow flow, low evaporation)
- Vertical seepage between layers
- Horizontal flow based on hydraulic pressure

Water quantities are in integer units matching depth units (1 unit = 100mm).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from ground import (
    TerrainColumn,
    SoilLayer,
    MATERIAL_LIBRARY,
    layers_can_connect,
)
from utils import get_neighbors
from config import (
    SUBSURFACE_FLOW_RATE,
    VERTICAL_SEEPAGE_RATE,
    CAPILLARY_RISE_RATE,
    SUBSURFACE_FLOW_THRESHOLD,
)

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


def _calculate_seep(
        source_water: int,
        permeability: int,
        rate_pct: int,
        capacity: int,
) -> int:
    """Helper to calculate how much water can seep."""
    if source_water <= 0 or capacity <= 0:
        return 0

    seep_potential = (source_water * permeability * rate_pct) // 10000
    return min(seep_potential, capacity, source_water)


def _calculate_hydraulic_head(terrain: TerrainColumn, water: WaterColumn, layer: SoilLayer) -> int:
    """Calculate hydraulic head (pressure) for a layer."""
    bottom, top = terrain.get_layer_elevation_range(layer)

    water_in_layer = water.get_layer_water(layer)
    max_storage = terrain.get_max_water_storage(layer)

    if max_storage > 0 and water_in_layer > 0:
        # Water fills from bottom up
        layer_depth = top - bottom
        # Allow head to calculate for over-capacity water
        water_height = (water_in_layer * layer_depth) // max_storage
        return bottom + water_height

    return bottom  # Empty layer has minimum head


def simulate_vertical_seepage(terrain: TerrainColumn, water: WaterColumn, surface_water_total: int = 0) -> int:
    """
    Simulate water seeping vertically through soil layers, one layer at a time.
    This version prevents the "waterfall" bug.

    Args:
        terrain: Terrain column for layer properties
        water: Water column for subsurface water storage
        surface_water_total: Total surface water on this tile's sub-squares (for capillary check)

    Returns:
        Amount of water to distribute to surface via capillary rise
    """
    # --- Downward Seepage between soil layers ---
    # Note: Surface-to-soil seepage is handled per-sub-square in simulation/surface.py

    # 1. Seep between adjacent soil layers (one step at a time)
    # Create a list of transfers to apply atomically, preventing the waterfall effect.
    transfers: Dict[SoilLayer, int] = defaultdict(int)
    soil_layers = list(reversed(SoilLayer))  # [Organics, Topsoil, ..., Bedrock]
    for i in range(len(soil_layers) - 1):
        from_layer, to_layer = soil_layers[i], soil_layers[i + 1]
        if to_layer == SoilLayer.BEDROCK: continue

        source_water = water.get_layer_water(from_layer)
        if source_water <= 0: continue

        available_capacity = terrain.get_max_water_storage(to_layer) - water.get_layer_water(to_layer)
        if available_capacity <= 0: continue

        props = MATERIAL_LIBRARY.get(terrain.get_layer_material(from_layer))
        if props:
            seep_amount = _calculate_seep(
                source_water,
                props.permeability_vertical,
                VERTICAL_SEEPAGE_RATE,
                available_capacity
            )
            if seep_amount > 0:
                transfers[from_layer] -= seep_amount
                transfers[to_layer] += seep_amount

    # Apply all the calculated transfers at once
    for layer, delta in transfers.items():
        water.add_layer_water(layer, delta)

    # 2. Bedrock pressure: push water up from oversaturated Regolith
    regolith_capacity = terrain.get_max_water_storage(SoilLayer.REGOLITH)
    regolith_water = water.get_layer_water(SoilLayer.REGOLITH)
    if regolith_water > regolith_capacity:
        excess = regolith_water - regolith_capacity
        water.set_layer_water(SoilLayer.REGOLITH, regolith_capacity)
        water.add_layer_water(SoilLayer.SUBSOIL, excess)  # Push up to subsoil

    # --- Upward Movement (Capillary Action) ---
    # Only rise if surface is relatively dry (less than 1cm equivalent)
    capillary_rise = 0
    if surface_water_total < 10:
        # Find topmost layer with water
        for layer in [SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION]:
            if terrain.get_layer_depth(layer) > 0 and water.get_layer_water(layer) > 0:
                material = terrain.get_layer_material(layer)
                props = MATERIAL_LIBRARY.get(material)
                if props:
                    source_water = water.get_layer_water(layer)
                    rise_amount = _calculate_seep(
                        source_water,
                        props.permeability_vertical,
                        CAPILLARY_RISE_RATE,
                        source_water  # Effectively unlimited capacity
                    )
                    if rise_amount > 0:
                        water.remove_layer_water(layer, rise_amount)
                        capillary_rise = rise_amount
                break  # Only rise from the single topmost wet layer

    return capillary_rise


def calculate_subsurface_flow(
        tiles: List[List[Tuple[TerrainColumn, WaterColumn]]],
        width: int,
        height: int,
) -> Dict[Tuple[Point, SoilLayer], int]:
    """
    Calculate subsurface water flow based on hydraulic pressure.
    Returns a dictionary of deltas (positive for gain, negative for loss).
    """
    deltas: Dict[Tuple[Point, SoilLayer], int] = defaultdict(int)

    # Process each soil layer (skip bedrock)
    for layer in [SoilLayer.REGOLITH, SoilLayer.SUBSOIL, SoilLayer.ELUVIATION,
                  SoilLayer.TOPSOIL, SoilLayer.ORGANICS]:

        for x in range(width):
            for y in range(height):
                terrain, water = tiles[x][y]

                # Skip if layer doesn't exist or has no water
                if terrain.get_layer_depth(layer) == 0:
                    continue
                if water.get_layer_water(layer) == 0:
                    continue

                material = terrain.get_layer_material(layer)
                props = MATERIAL_LIBRARY.get(material)
                if not props:
                    continue

                # Calculate my hydraulic head
                my_head = _calculate_hydraulic_head(terrain, water, layer)

                # Check neighbors
                flow_targets = []
                total_diff = 0

                for nx, ny in get_neighbors(x, y, width, height):
                    n_terrain, n_water = tiles[nx][ny]

                    # Skip if neighbor doesn't have this layer
                    if n_terrain.get_layer_depth(layer) == 0:
                        continue

                    # Skip if layers don't overlap in elevation (bedrock blocks flow)
                    if not layers_can_connect(terrain, layer, n_terrain, layer):
                        continue

                    n_head = _calculate_hydraulic_head(n_terrain, n_water, layer)
                    diff = my_head - n_head

                    if diff > SUBSURFACE_FLOW_THRESHOLD:
                        flow_targets.append(((nx, ny), diff))
                        total_diff += diff

                if not flow_targets:
                    continue

                # Subsurface flow is slow
                water_available = water.get_layer_water(layer)
                flow_pct = (props.permeability_horizontal * SUBSURFACE_FLOW_RATE) // 100
                transferable = (water_available * flow_pct) // 100

                # Distribute proportionally
                total_transferred = 0
                for (nx, ny), diff in flow_targets:
                    portion = (transferable * diff) // total_diff if total_diff > 0 else 0
                    if portion > 0:
                        key = ((nx, ny), layer)
                        deltas[key] += portion
                        total_transferred += portion

                if total_transferred > 0:
                    source_key = ((x, y), layer)
                    deltas[source_key] -= total_transferred

    return deltas


def calculate_overflows(
        tiles: List[List[Tuple[TerrainColumn, WaterColumn]]],
        width: int,
        height: int,
) -> Tuple[Dict[Tuple[Point, SoilLayer], int], Dict[Point, int]]:
    """
    Calculates distribution of water in layers that are over capacity.
    This is a high-pressure, rapid version of subsurface flow.
    Returns (subsurface_deltas, surface_deltas).
    """
    sub_deltas: Dict[Tuple[Point, SoilLayer], int] = defaultdict(int)
    surf_deltas: Dict[Point, int] = defaultdict(int)

    for layer in reversed(SoilLayer): # Process from top down
        if layer == SoilLayer.BEDROCK: continue

        for x in range(width):
            for y in range(height):
                terrain, water = tiles[x][y]
                max_storage = terrain.get_max_water_storage(layer)
                current_water = water.get_layer_water(layer)

                if current_water <= max_storage:
                    continue

                overflow_amount = current_water - max_storage
                my_head = _calculate_hydraulic_head(terrain, water, layer)

                # Find neighbors to overflow into
                flow_targets = []
                total_diff = 0
                for nx, ny in get_neighbors(x, y, width, height):
                    n_terrain, n_water = tiles[nx][ny]
                    if n_terrain.get_layer_depth(layer) == 0: continue

                    # Skip if layers don't overlap in elevation (bedrock blocks flow)
                    if not layers_can_connect(terrain, layer, n_terrain, layer):
                        continue

                    n_head = _calculate_hydraulic_head(n_terrain, n_water, layer)
                    diff = my_head - n_head
                    if diff > 0: # Flow to any lower pressure neighbor
                        flow_targets.append(((nx, ny), diff))
                        total_diff += diff

                if not flow_targets:
                    # If no neighbors, water is pushed to the surface
                    sub_deltas[((x, y), layer)] -= overflow_amount
                    surf_deltas[(x, y)] += overflow_amount
                    continue

                # Distribute overflow to neighbors
                total_transferred = 0
                for (nx, ny), diff in flow_targets:
                    portion = (overflow_amount * diff) // total_diff if total_diff > 0 else 0
                    if portion > 0:
                        sub_deltas[((nx, ny), layer)] += portion
                        total_transferred += portion

                if total_transferred > 0:
                    sub_deltas[((x, y), layer)] -= total_transferred

    return sub_deltas, surf_deltas
