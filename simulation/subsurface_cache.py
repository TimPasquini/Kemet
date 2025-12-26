# simulation/subsurface_cache.py
"""
Connectivity cache for subsurface simulation optimization.

Caches terrain-dependent geometric calculations (layer connectivity, contact fractions)
that don't change unless terrain is modified. This eliminates the most expensive
bottleneck in subsurface flow calculations (42.8% of subsurface time).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Tuple, Optional
import numpy as np

from world.terrain import SoilLayer
from config import GRID_WIDTH, GRID_HEIGHT

if TYPE_CHECKING:
    from game_state import GameState


class SubsurfaceConnectivityCache:
    """Cache for terrain-dependent subsurface connectivity calculations.

    This cache stores pre-computed geometric data about layer connectivity,
    which only changes when terrain is modified (erosion, player actions).

    Cached data includes:
    - Padded elevation arrays for neighbor access
    - Connection masks showing which layer pairs can physically connect
    - Contact fractions showing overlap between connected layers

    The cache can operate in two modes:
    1. Invalidation-based: Only rebuild when explicitly invalidated (default)
    2. Periodic: Rebuild every N ticks (paranoid mode for debugging)
    """

    def __init__(self, rebuild_frequency_ticks: Optional[int] = None):
        """Initialize the connectivity cache.

        Args:
            rebuild_frequency_ticks: If set, cache rebuilds every N ticks regardless
                                    of invalidation. None = only rebuild on invalidate.
                                    Useful values:
                                    - None: Trust explicit invalidation (fastest)
                                    - 300: Rebuild every 300 ticks (paranoid debug)
                                    - DAY_LENGTH//4: Rebuild with erosion events
        """
        # === Cached Geometric Data ===
        # Padded elevation arrays for all layers (for neighbor lookups)
        self.layer_bottom_padded: Optional[np.ndarray] = None  # Shape: (6, W+2, H+2)
        self.layer_top_padded: Optional[np.ndarray] = None     # Shape: (6, W+2, H+2)
        self.terrain_layers_padded: Optional[np.ndarray] = None # Shape: (6, W+2, H+2)

        # Connection masks: Dict[(src_layer, dx, dy, tgt_layer)] -> bool array (W, H)
        # True where source layer at (x,y) can connect to target layer at (x+dx, y+dy)
        self.connection_masks: Dict[Tuple[int, int, int, int], np.ndarray] = {}

        # Contact fractions: Dict[(src_layer, dx, dy, tgt_layer)] -> float array (W, H)
        # Fraction of source layer height that overlaps with target layer
        self.contact_fractions: Dict[Tuple[int, int, int, int], np.ndarray] = {}

        # === Cache Validity Tracking ===
        self.is_valid: bool = False
        self.rebuild_frequency: Optional[int] = rebuild_frequency_ticks
        self.ticks_since_rebuild: int = 0

        # === Statistics (for debugging/tuning) ===
        self.rebuild_count: int = 0
        self.invalidate_count: int = 0

    def needs_rebuild(self) -> bool:
        """Check if cache needs rebuilding.

        Returns:
            True if cache should be rebuilt before use
        """
        # Cache was explicitly invalidated
        if not self.is_valid:
            return True

        # Periodic rebuild (if configured)
        if self.rebuild_frequency is not None:
            if self.ticks_since_rebuild >= self.rebuild_frequency:
                return True

        return False

    def rebuild(self, state: "GameState") -> None:
        """Rebuild entire cache from current terrain state.

        This is expensive (several ms), but only needs to happen when terrain changes.

        Args:
            state: Game state with current terrain data
        """
        from simulation.subsurface_vectorized import compute_layer_elevation_ranges

        # Get current layer elevations
        layer_bottom, layer_top = compute_layer_elevation_ranges(state)

        # Pad all elevation arrays for neighbor access
        self.layer_bottom_padded = np.pad(
            layer_bottom, ((0, 0), (1, 1), (1, 1)),
            mode='constant', constant_values=0
        )
        self.layer_top_padded = np.pad(
            layer_top, ((0, 0), (1, 1), (1, 1)),
            mode='constant', constant_values=0
        )
        self.terrain_layers_padded = np.pad(
            state.terrain_layers, ((0, 0), (1, 1), (1, 1)),
            mode='constant', constant_values=0
        )

        # Clear old connectivity data
        self.connection_masks.clear()
        self.contact_fractions.clear()

        # Pre-compute connectivity for all layer pairs and directions
        flowable_layers = [
            SoilLayer.REGOLITH,
            SoilLayer.SUBSOIL,
            SoilLayer.ELUVIATION,
            SoilLayer.TOPSOIL,
            SoilLayer.ORGANICS
        ]

        neighbor_offsets = [(1, 0), (-1, 0), (0, 1), (0, -1)]

        for src_layer in flowable_layers:
            my_bot = layer_bottom[src_layer]
            my_top = layer_top[src_layer]
            my_height = my_top - my_bot

            for dx, dy in neighbor_offsets:
                # Neighbor slice in padded arrays
                n_slice = (
                    slice(1 + dx, -1 + dx if -1 + dx != 0 else None),
                    slice(1 + dy, -1 + dy if -1 + dy != 0 else None)
                )

                for tgt_layer_idx in range(len(SoilLayer)):
                    if tgt_layer_idx == SoilLayer.BEDROCK:
                        continue  # Skip bedrock

                    # Get neighbor's layer elevation range
                    neighbor_bot = self.layer_bottom_padded[tgt_layer_idx][n_slice]
                    neighbor_top = self.layer_top_padded[tgt_layer_idx][n_slice]
                    neighbor_depth = self.terrain_layers_padded[tgt_layer_idx][n_slice]

                    # Check if layers overlap in elevation (can connect)
                    can_connect = (
                        (my_bot < neighbor_top) &
                        (neighbor_bot < my_top) &
                        (neighbor_depth > 0)
                    )

                    # Skip if no connections possible anywhere
                    if not np.any(can_connect):
                        continue

                    # Calculate contact area fraction (how much of my layer touches neighbor)
                    overlap_bot = np.maximum(my_bot, neighbor_bot)
                    overlap_top = np.minimum(my_top, neighbor_top)
                    overlap_height = np.maximum(overlap_top - overlap_bot, 0)

                    # Contact fraction = overlap_height / my_layer_height
                    contact_fraction = np.divide(
                        overlap_height,
                        my_height,
                        out=np.zeros_like(overlap_height, dtype=np.float32),
                        where=my_height > 0
                    )

                    # Store in cache
                    key = (src_layer, dx, dy, tgt_layer_idx)
                    self.connection_masks[key] = can_connect.copy()
                    self.contact_fractions[key] = contact_fraction.copy()

        # Mark cache as valid
        self.is_valid = True
        self.ticks_since_rebuild = 0
        self.rebuild_count += 1

    def invalidate(self) -> None:
        """Mark cache as invalid - terrain has changed.

        Call this whenever terrain is modified:
        - Player digs, lowers, raises terrain
        - Erosion occurs
        - Any modification to terrain_layers or bedrock_base
        """
        self.is_valid = False
        self.invalidate_count += 1

    def tick(self) -> None:
        """Update tick counter for periodic rebuild.

        Call this every subsurface tick to track time since last rebuild.
        Only relevant if rebuild_frequency is set.
        """
        if self.rebuild_frequency is not None:
            self.ticks_since_rebuild += 1

    def get_padded_elevations(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Get padded elevation arrays.

        Returns:
            (layer_bottom_padded, layer_top_padded, terrain_layers_padded)

        Raises:
            RuntimeError: If cache is not valid
        """
        if not self.is_valid:
            raise RuntimeError("Cache is invalid - call rebuild() first")

        return (
            self.layer_bottom_padded,
            self.layer_top_padded,
            self.terrain_layers_padded
        )

    def get_connectivity(
        self,
        src_layer: int,
        dx: int,
        dy: int,
        tgt_layer: int
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """Get cached connectivity data for a specific layer pair.

        Args:
            src_layer: Source layer index
            dx, dy: Direction offset (-1, 0, or 1)
            tgt_layer: Target layer index

        Returns:
            (connection_mask, contact_fraction) if connection exists, else (None, None)

        Raises:
            RuntimeError: If cache is not valid
        """
        if not self.is_valid:
            raise RuntimeError("Cache is invalid - call rebuild() first")

        key = (src_layer, dx, dy, tgt_layer)

        if key not in self.connection_masks:
            return None, None

        return self.connection_masks[key], self.contact_fractions[key]

    def get_all_connections(
        self,
        src_layer: int
    ) -> list[Tuple[int, int, int, np.ndarray, np.ndarray]]:
        """Get all cached connections for a source layer.

        Args:
            src_layer: Source layer index

        Returns:
            List of (dx, dy, tgt_layer, connection_mask, contact_fraction) tuples

        Raises:
            RuntimeError: If cache is not valid
        """
        if not self.is_valid:
            raise RuntimeError("Cache is invalid - call rebuild() first")

        connections = []
        for key, mask in self.connection_masks.items():
            src, dx, dy, tgt = key
            if src == src_layer:
                fraction = self.contact_fractions[key]
                connections.append((dx, dy, tgt, mask, fraction))

        return connections

    def get_stats(self) -> dict:
        """Get cache statistics for debugging/tuning.

        Returns:
            Dictionary with cache statistics
        """
        return {
            'is_valid': self.is_valid,
            'rebuild_count': self.rebuild_count,
            'invalidate_count': self.invalidate_count,
            'ticks_since_rebuild': self.ticks_since_rebuild,
            'rebuild_frequency': self.rebuild_frequency,
            'num_connections': len(self.connection_masks),
            'memory_estimate_mb': self._estimate_memory_usage() / 1024 / 1024,
        }

    def _estimate_memory_usage(self) -> int:
        """Estimate cache memory usage in bytes.

        Returns:
            Estimated memory usage in bytes
        """
        total_bytes = 0

        # Padded arrays
        if self.layer_bottom_padded is not None:
            total_bytes += self.layer_bottom_padded.nbytes
            total_bytes += self.layer_top_padded.nbytes
            total_bytes += self.terrain_layers_padded.nbytes

        # Connection masks and fractions
        for mask in self.connection_masks.values():
            total_bytes += mask.nbytes
        for fraction in self.contact_fractions.values():
            total_bytes += fraction.nbytes

        return total_bytes
