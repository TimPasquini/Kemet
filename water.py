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

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

from ground import (
    TerrainColumn,
    SoilLayer,
    MATERIAL_LIBRARY,
    SEA_LEVEL,
)

# Flow rate constants (as percentages: 0-100)
SURFACE_FLOW_RATE = 50          # Fast surface flow (50% per tick)
SUBSURFACE_FLOW_RATE = 8        # Slow subsurface flow (8% per tick)
VERTICAL_SEEPAGE_RATE = 30      # Vertical seepage speed (30% per tick)
CAPILLARY_RISE_RATE = 5         # Capillary rise is much slower (5% per tick)

# Flow threshold constants (in depth units)
SURFACE_FLOW_THRESHOLD = 1      # Minimum elevation difference for surface flow (~1cm)
SUBSURFACE_FLOW_THRESHOLD = 1   # Minimum pressure difference for subsurface flow

Point = Tuple[int, int]


@dataclass
class WaterColumn:
    """
    Water storage for a tile using fixed soil layers.
    
    Each layer stores water as integer units (1 unit = 100mm).
    Water fills based on layer porosity and material properties.
    """
    # Water in each fixed layer (parallel to TerrainColumn layers)
    bedrock_water: int = 0      # Should generally be 0 (bedrock is impermeable)
    regolith_water: int = 0
    subsoil_water: int = 0
    eluviation_water: int = 0
    topsoil_water: int = 0
    organics_water: int = 0
    
    # Water above ground surface
    surface_water: int = 0
    
    def get_layer_water(self, layer: SoilLayer) -> int:
        """Get water amount in a specific layer."""
        if layer == SoilLayer.BEDROCK:
            return self.bedrock_water
        elif layer == SoilLayer.REGOLITH:
            return self.regolith_water
        elif layer == SoilLayer.SUBSOIL:
            return self.subsoil_water
        elif layer == SoilLayer.ELUVIATION:
            return self.eluviation_water
        elif layer == SoilLayer.TOPSOIL:
            return self.topsoil_water
        elif layer == SoilLayer.ORGANICS:
            return self.organics_water
        return 0
    
    def set_layer_water(self, layer: SoilLayer, amount: int) -> None:
        """Set water amount in a specific layer."""
        amount = max(0, amount)  # Can't have negative water
        
        if layer == SoilLayer.BEDROCK:
            self.bedrock_water = amount
        elif layer == SoilLayer.REGOLITH:
            self.regolith_water = amount
        elif layer == SoilLayer.SUBSOIL:
            self.subsoil_water = amount
        elif layer == SoilLayer.ELUVIATION:
            self.eluviation_water = amount
        elif layer == SoilLayer.TOPSOIL:
            self.topsoil_water = amount
        elif layer == SoilLayer.ORGANICS:
            self.organics_water = amount
    
    def add_layer_water(self, layer: SoilLayer, amount: int) -> None:
        """Add water to a specific layer."""
        current = self.get_layer_water(layer)
        self.set_layer_water(layer, current + amount)
    
    def remove_layer_water(self, layer: SoilLayer, amount: int) -> int:
        """
        Remove water from a layer.
        
        Returns actual amount removed (may be less if insufficient water).
        """
        current = self.get_layer_water(layer)
        actual = min(amount, current)
        self.set_layer_water(layer, current - actual)
        return actual
    
    def total_water(self) -> int:
        """Total water in entire column (surface + all layers)."""
        return (self.surface_water + 
                self.bedrock_water +
                self.regolith_water + 
                self.subsoil_water + 
                self.eluviation_water + 
                self.topsoil_water + 
                self.organics_water)
    
    def total_subsurface_water(self) -> int:
        """Total water in all subsurface layers."""
        return (self.bedrock_water +
                self.regolith_water + 
                self.subsoil_water + 
                self.eluviation_water + 
                self.topsoil_water + 
                self.organics_water)


def simulate_vertical_seepage(terrain: TerrainColumn, water: WaterColumn) -> None:
    """
    Simulate water seeping vertically through soil layers.
    
    Water seeps down from surface -> organics -> topsoil -> eluviation -> subsoil -> regolith.
    Capillary action can bring water back up when surface layers are dry.
    """
    # 1. Seep surface water into organics layer (or topsoil if no organics)
    if water.surface_water > 0:
        # Find topmost non-empty soil layer
        target_layer = None
        if terrain.organics_depth > 0:
            target_layer = SoilLayer.ORGANICS
        elif terrain.topsoil_depth > 0:
            target_layer = SoilLayer.TOPSOIL
        elif terrain.eluviation_depth > 0:
            target_layer = SoilLayer.ELUVIATION
        elif terrain.subsoil_depth > 0:
            target_layer = SoilLayer.SUBSOIL
        elif terrain.regolith_depth > 0:
            target_layer = SoilLayer.REGOLITH
        
        if target_layer is not None:
            material = terrain.get_layer_material(target_layer)
            props = MATERIAL_LIBRARY.get(material)
            if props:
                max_storage = terrain.get_max_water_storage(target_layer)
                current_water = water.get_layer_water(target_layer)
                available_capacity = max_storage - current_water
                
                if available_capacity > 0:
                    # Calculate seepage amount
                    seep_rate = (water.surface_water * props.permeability_vertical * VERTICAL_SEEPAGE_RATE) // 10000
                    seep_amount = min(seep_rate, available_capacity, water.surface_water)
                    
                    if seep_amount > 0:
                        water.surface_water -= seep_amount
                        water.add_layer_water(target_layer, seep_amount)
    
    # 2. Seep between soil layers (top to bottom)
    layer_sequence = [
        SoilLayer.ORGANICS,
        SoilLayer.TOPSOIL,
        SoilLayer.ELUVIATION,
        SoilLayer.SUBSOIL,
        SoilLayer.REGOLITH,
    ]
    
    for i in range(len(layer_sequence) - 1):
        from_layer = layer_sequence[i]
        to_layer = layer_sequence[i + 1]
        
        # Skip if source layer doesn't exist or has no water
        if terrain.get_layer_depth(from_layer) == 0:
            continue
        if water.get_layer_water(from_layer) == 0:
            continue
        
        # Skip if target layer doesn't exist
        if terrain.get_layer_depth(to_layer) == 0:
            continue
        
        material = terrain.get_layer_material(from_layer)
        props = MATERIAL_LIBRARY.get(material)
        if not props:
            continue
        
        max_storage = terrain.get_max_water_storage(to_layer)
        current_water = water.get_layer_water(to_layer)
        available_capacity = max_storage - current_water
        
        if available_capacity > 0:
            source_water = water.get_layer_water(from_layer)
            seep_rate = (source_water * props.permeability_vertical * VERTICAL_SEEPAGE_RATE) // 10000
            seep_amount = min(seep_rate, available_capacity, source_water)
            
            if seep_amount > 0:
                water.remove_layer_water(from_layer, seep_amount)
                water.add_layer_water(to_layer, seep_amount)
    
    # 3. Capillary rise: subsurface water rises when surface is dry
    if water.surface_water < 10:  # Less than 1cm of surface water
        # Find topmost layer with water
        for layer in [SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION]:
            if terrain.get_layer_depth(layer) > 0 and water.get_layer_water(layer) > 0:
                material = terrain.get_layer_material(layer)
                props = MATERIAL_LIBRARY.get(material)
                if props:
                    source_water = water.get_layer_water(layer)
                    rise_rate = (source_water * props.permeability_vertical * CAPILLARY_RISE_RATE) // 10000
                    rise_amount = min(rise_rate, source_water)
                    
                    if rise_amount > 0:
                        water.remove_layer_water(layer, rise_amount)
                        water.surface_water += rise_amount
                break  # Only rise from topmost wet layer


def calculate_surface_flow(
    tiles: List[List[Tuple[TerrainColumn, WaterColumn]]],
    width: int,
    height: int,
    trench_map: Dict[Point, bool],
) -> Dict[Point, int]:
    """
    Calculate surface water flow based on surface elevation + water depth.
    
    Water flows from higher surfaces to lower surfaces.
    Trenches increase flow rate.
    """
    flows: Dict[Point, int] = {}
    
    def get_neighbors(x: int, y: int) -> List[Point]:
        """Get valid orthogonal neighbors."""
        result = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < width and 0 <= ny < height:
                result.append((nx, ny))
        return result
    
    for x in range(width):
        for y in range(height):
            terrain, water = tiles[x][y]
            
            if water.surface_water == 0:
                continue
            
            # Surface height = terrain surface + water depth
            my_surface = terrain.get_surface_elevation() + water.surface_water
            
            # Find lower neighbors
            flow_targets = []
            total_diff = 0
            
            for nx, ny in get_neighbors(x, y):
                n_terrain, n_water = tiles[nx][ny]
                n_surface = n_terrain.get_surface_elevation() + n_water.surface_water
                diff = my_surface - n_surface
                
                if diff > SURFACE_FLOW_THRESHOLD:
                    flow_targets.append(((nx, ny), diff))
                    total_diff += diff
            
            if not flow_targets:
                continue
            
            # Calculate flow rate (percentage of available water)
            flow_pct = SURFACE_FLOW_RATE
            
            # Trenches increase surface flow
            if trench_map.get((x, y), False):
                flow_pct = (flow_pct * 150) // 100  # 1.5x multiplier
            
            transferable = (water.surface_water * flow_pct) // 100
            
            # Distribute proportionally to elevation differences
            total_transferred = 0
            for (nx, ny), diff in flow_targets:
                portion = (transferable * diff) // total_diff
                if portion > 0:
                    flows[(nx, ny)] = flows.get((nx, ny), 0) + portion
                    total_transferred += portion
            
            water.surface_water -= total_transferred
    
    return flows


def calculate_subsurface_flow(
    tiles: List[List[Tuple[TerrainColumn, WaterColumn]]],
    width: int,
    height: int,
) -> Dict[Tuple[Point, SoilLayer], int]:
    """
    Calculate subsurface water flow based on hydraulic pressure.
    
    Water flows between corresponding layers in neighboring tiles.
    Much slower than surface flow.
    """
    flows: Dict[Tuple[Point, SoilLayer], int] = {}
    
    def get_neighbors(x: int, y: int) -> List[Point]:
        """Get valid orthogonal neighbors."""
        result = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < width and 0 <= ny < height:
                result.append((nx, ny))
        return result
    
    def calculate_hydraulic_head(terrain: TerrainColumn, water: WaterColumn, layer: SoilLayer) -> int:
        """Calculate hydraulic head (pressure) for a layer."""
        bottom, top = terrain.get_layer_elevation_range(layer)
        
        water_in_layer = water.get_layer_water(layer)
        max_storage = terrain.get_max_water_storage(layer)
        
        if max_storage > 0 and water_in_layer > 0:
            # Water fills from bottom up
            layer_depth = top - bottom
            water_height = (water_in_layer * layer_depth) // max_storage
            return bottom + water_height
        
        return bottom  # Empty layer has minimum head
    
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
                my_head = calculate_hydraulic_head(terrain, water, layer)
                
                # Check neighbors
                flow_targets = []
                total_diff = 0
                
                for nx, ny in get_neighbors(x, y):
                    n_terrain, n_water = tiles[nx][ny]
                    
                    # Skip if neighbor doesn't have this layer
                    if n_terrain.get_layer_depth(layer) == 0:
                        continue
                    
                    n_head = calculate_hydraulic_head(n_terrain, n_water, layer)
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
                    portion = (transferable * diff) // total_diff
                    if portion > 0:
                        key = ((nx, ny), layer)
                        flows[key] = flows.get(key, 0) + portion
                        total_transferred += portion
                
                water.remove_layer_water(layer, total_transferred)
    
    return flows


def apply_flows(
    tiles: List[List[Tuple[TerrainColumn, WaterColumn]]],
    surface_flows: Dict[Point, int],
    subsurface_flows: Dict[Tuple[Point, SoilLayer], int],
) -> None:
    """Apply accumulated water flows to tiles."""
    # Apply surface flows
    for (x, y), amount in surface_flows.items():
        _, water = tiles[x][y]
        water.surface_water += amount
    
    # Apply subsurface flows
    for ((x, y), layer), amount in subsurface_flows.items():
        _, water = tiles[x][y]
        water.add_layer_water(layer, amount)
