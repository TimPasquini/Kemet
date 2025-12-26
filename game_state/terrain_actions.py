# game_state/terrain_actions.py
"""Terrain modification actions (dig trench, lower/raise ground)."""
from __future__ import annotations

from typing import TYPE_CHECKING, List
import math

import numpy as np

from config import (
        GRID_WIDTH,
    GRID_HEIGHT,
    MIN_BEDROCK_ELEVATION,
    TRENCH_SLOPE_DROP,
)
from world.terrain import (
    SoilLayer,
    units_to_meters,
)

if TYPE_CHECKING:
    from game_state.state import GameState


def _get_perpendicular_neighbors(px: int, py: int, tx: int, ty: int, grid_width: int, grid_height: int) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """Get left and right perpendicular neighbors relative to player-target direction.

    Args:
        px, py: Player position (grid coords)
        tx, ty: Target position (grid coords)
        grid_width, grid_height: Grid bounds

    Returns:
        (left_neighbor, right_neighbor) tuples or None if out of bounds
    """
    # Direction vector from player to target
    dx = tx - px
    dy = ty - py

    # Perpendicular vectors (rotate 90°)
    # Left (CCW): (dx, dy) → (-dy, dx)
    # Right (CW): (dx, dy) → (dy, -dx)
    left_dx, left_dy = -dy, dx
    right_dx, right_dy = dy, -dx

    # Normalize to unit length (or closest grid cell)
    left_len = math.sqrt(left_dx**2 + left_dy**2)
    right_len = math.sqrt(right_dx**2 + right_dy**2)

    if left_len > 0:
        left_dx = round(left_dx / left_len)
        left_dy = round(left_dy / left_len)
    if right_len > 0:
        right_dx = round(right_dx / right_len)
        right_dy = round(right_dy / right_len)

    # Calculate neighbor positions
    left_pos = (tx + left_dx, ty + left_dy)
    right_pos = (tx + right_dx, ty + right_dy)

    # Check bounds
    left_valid = 0 <= left_pos[0] < grid_width and 0 <= left_pos[1] < grid_height
    right_valid = 0 <= right_pos[0] < grid_width and 0 <= right_pos[1] < grid_height

    return (left_pos if left_valid else None, right_pos if right_valid else None)


def dig_trench(state: GameState, mode: str) -> None:
    """Dig a trench with the specified mode: 'flat', 'slope_down', or 'slope_up'.

    Common setup handles position calculation and validation.
    Mode-specific logic handles material removal and redistribution.

    Args:
        state: Game state
        mode: One of 'flat', 'slope_down', 'slope_up'
    """
    # ========== COMMON SETUP ==========
    sub_pos = state.get_action_target_cell()
    sx, sy = sub_pos
    px, py = state.player_cell

    # Get perpendicular neighbors (for berms)
    left_pos, right_pos = _get_perpendicular_neighbors(px, py, sx, sy, GRID_WIDTH, GRID_HEIGHT)

    # Get axial direction
    dx, dy = sx - px, sy - py
    length = math.sqrt(dx**2 + dy**2)
    if length > 0:
        dx_norm, dy_norm = round(dx / length), round(dy / length)
    else:
        state.messages.append("Cannot trench at player position.")
        return

    # Calculate origin (backward) and exit (forward) positions
    backward_pos = (sx - dx_norm, sy - dy_norm)
    forward_pos = (sx + dx_norm, sy + dy_norm)

    # Validate positions
    if not (0 <= backward_pos[0] < GRID_WIDTH and 0 <= backward_pos[1] < GRID_HEIGHT):
        state.messages.append("Cannot trench - invalid origin position.")
        return
    if mode in ["slope_down", "slope_up"]:
        if not (0 <= forward_pos[0] < GRID_WIDTH and 0 <= forward_pos[1] < GRID_HEIGHT):
            state.messages.append("Cannot trench - invalid exit position.")
            return

    # Get current elevations
    origin_elev = state.elevation_grid[backward_pos]
    target_elev = state.elevation_grid[sx, sy]
    exit_elev = state.elevation_grid[forward_pos] if mode in ["slope_down", "slope_up"] else None

    # ========== MODE-SPECIFIC LOGIC ==========
    match mode:
        case "flat":
            _dig_trench_flat_impl(state, sx, sy, origin_elev, target_elev,
                                 backward_pos, forward_pos, left_pos, right_pos)
        case "slope_down":
            _dig_trench_slope_down_impl(state, sx, sy, origin_elev, target_elev, exit_elev,
                                       backward_pos, forward_pos, left_pos, right_pos)
        case "slope_up":
            _dig_trench_slope_up_impl(state, sx, sy, origin_elev, target_elev, exit_elev,
                                     backward_pos, forward_pos, left_pos, right_pos)
        case _:
            state.messages.append(f"Unknown trench mode: {mode}")
            return  # Don't invalidate cache if mode was invalid

    # Terrain was modified - invalidate subsurface connectivity cache
    if state.subsurface_cache is not None:
        state.subsurface_cache.invalidate()


def _dig_trench_flat_impl(state: GameState, sx: int, sy: int,
                          origin_elev: int, target_elev: int,
                          backward_pos: tuple, forward_pos: tuple,
                          left_pos: tuple, right_pos: tuple) -> None:
    """Implementation of flat trenching mode."""
    # Find exposed layer at target (top to bottom)
    exposed_layer = None
    for layer in [SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION,
                  SoilLayer.SUBSOIL, SoilLayer.REGOLITH]:
        if state.terrain_layers[layer, sx, sy] > 0:
            exposed_layer = layer
            break

    if exposed_layer is None:
        state.messages.append("Cannot trench bedrock.")
        return

    # Calculate how much to modify target
    elevation_diff = target_elev - origin_elev

    if elevation_diff <= 0:
        # Target is already at or below origin - no trenching needed
        state.messages.append(f"Target already at channel level (origin: {units_to_meters(origin_elev):.2f}m).")
        return

    # AUTO-COMPLETE: Remove ALL material needed to reach origin level (not just TRENCH_DEPTH)
    material_to_remove = min(elevation_diff, state.terrain_layers[exposed_layer, sx, sy])

    if material_to_remove == 0:
        state.messages.append("No material to remove.")
        return

    # Remove from target
    state.terrain_layers[exposed_layer, sx, sy] -= material_to_remove
    if state.terrain_layers[exposed_layer, sx, sy] == 0:
        state.terrain_materials[exposed_layer, sx, sy] = ""

    # Distribute material with priority: exit → lower side → even split
    material_pool = material_to_remove

    # PRIORITY 1: Fill forward (exit) to origin level
    if (0 <= forward_pos[0] < GRID_WIDTH and 0 <= forward_pos[1] < GRID_HEIGHT):
        forward_elev = state.elevation_grid[forward_pos]
        if forward_elev < origin_elev and material_pool > 0:
            forward_deficit = origin_elev - forward_elev
            fill_amount = min(material_pool, forward_deficit)
            layer = _get_or_create_layer(state, forward_pos[0], forward_pos[1])
            state.terrain_layers[layer, forward_pos[0], forward_pos[1]] += fill_amount
            state.dirty_cells.add(forward_pos)
            material_pool -= fill_amount

    # PRIORITY 2: Fill lower side to match higher side
    if material_pool > 0 and left_pos and right_pos:
        left_elev = state.elevation_grid[left_pos]
        right_elev = state.elevation_grid[right_pos]

        if left_elev < right_elev:
            # Fill left to match right
            deficit = right_elev - left_elev
            fill_amount = min(material_pool, deficit)
            layer = _get_or_create_layer(state, left_pos[0], left_pos[1])
            state.terrain_layers[layer, left_pos[0], left_pos[1]] += fill_amount
            state.dirty_cells.add(left_pos)
            material_pool -= fill_amount
        elif right_elev < left_elev:
            # Fill right to match left
            deficit = left_elev - right_elev
            fill_amount = min(material_pool, deficit)
            layer = _get_or_create_layer(state, right_pos[0], right_pos[1])
            state.terrain_layers[layer, right_pos[0], right_pos[1]] += fill_amount
            state.dirty_cells.add(right_pos)
            material_pool -= fill_amount

    # PRIORITY 3: Distribute remaining evenly to sides
    if material_pool > 0:
        recipients = []
        if left_pos:
            recipients.append(left_pos)
        if right_pos:
            recipients.append(right_pos)

        if recipients:
            per_recipient = material_pool // len(recipients)
            remainder = material_pool % len(recipients)

            for i, recipient in enumerate(recipients):
                layer = _get_or_create_layer(state, recipient[0], recipient[1])
                amount = per_recipient + (1 if i < remainder else 0)
                state.terrain_layers[layer, recipient[0], recipient[1]] += amount
                state.dirty_cells.add(recipient)

    # Mark changes
    state.dirty_cells.add((sx, sy))
    state.terrain_changed = True
    state.invalidate_elevation_range()

    state.messages.append(f"Trenched (flat): leveled to origin height, moved {units_to_meters(material_to_remove):.1f}m.")


def _find_exposed_layer(state: GameState, sx: int, sy: int) -> SoilLayer | None:
    """Find the exposed (topmost) layer at a cell, or None if bedrock."""
    for layer in [SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION,
                  SoilLayer.SUBSOIL, SoilLayer.REGOLITH]:
        if state.terrain_layers[layer, sx, sy] > 0:
            return layer
    return None


def _get_or_create_layer(state: GameState, sx: int, sy: int) -> SoilLayer:
    """Get the exposed (topmost) layer at a cell, or topsoil if bedrock exposed."""
    layer = _find_exposed_layer(state, sx, sy)
    return layer if layer is not None else SoilLayer.TOPSOIL


def _dig_trench_slope_down_impl(state: GameState, sx: int, sy: int,
                                origin_elev: int, target_elev: int, exit_elev: int,
                                backward_pos: tuple, forward_pos: tuple,
                                left_pos: tuple, right_pos: tuple) -> None:
    """Implementation of slope down trenching mode."""
    material_pool = 0

    # Goal: origin > selection > exit with TRENCH_SLOPE_DROP between each
    # Strategy: Pull from higher squares to raise lower ones

    # Check if exit is too high (higher than selection)
    if exit_elev > target_elev:
        # Pull from exit to raise selection
        exit_layer = _find_exposed_layer(state, forward_pos[0], forward_pos[1])
        if exit_layer is not None:
            material_from_exit = state.terrain_layers[exit_layer, forward_pos[0], forward_pos[1]]
            needed_for_selection = max(0, exit_elev - TRENCH_SLOPE_DROP - target_elev)
            to_remove_exit = min(material_from_exit, needed_for_selection)

            if to_remove_exit > 0:
                state.terrain_layers[exit_layer, forward_pos[0], forward_pos[1]] -= to_remove_exit
                if state.terrain_layers[exit_layer, forward_pos[0], forward_pos[1]] == 0:
                    state.terrain_materials[exit_layer, forward_pos[0], forward_pos[1]] = ""

                # Add to selection
                layer = _get_or_create_layer(state, sx, sy)
                state.terrain_layers[layer, sx, sy] += to_remove_exit
                state.dirty_cells.add(forward_pos)
                state.dirty_cells.add((sx, sy))

                # Update elevation for next check
                target_elev += to_remove_exit

    # Check if selection is too high relative to origin
    if target_elev > origin_elev:
        # Pull from selection to raise origin (halfway)
        exposed_layer = _find_exposed_layer(state, sx, sy)
        if exposed_layer is None:
            state.messages.append("Cannot trench bedrock.")
            return

        material_from_selection = state.terrain_layers[exposed_layer, sx, sy]
        if material_from_selection > 0:
            # Calculate halfway point
            max_fill_origin = target_elev - ((target_elev - origin_elev) // 2)
            deficit_origin = max(0, max_fill_origin - origin_elev)
            to_origin = min(material_from_selection, deficit_origin)

            if to_origin > 0:
                state.terrain_layers[exposed_layer, sx, sy] -= to_origin
                if state.terrain_layers[exposed_layer, sx, sy] == 0:
                    state.terrain_materials[exposed_layer, sx, sy] = ""

                # Fill origin
                layer = _get_or_create_layer(state, backward_pos[0], backward_pos[1])
                state.terrain_layers[layer, backward_pos[0], backward_pos[1]] += to_origin
                state.dirty_cells.add(backward_pos)
                state.dirty_cells.add((sx, sy))

            # Any remaining from selection goes to material pool for sides
            remaining = state.terrain_layers[exposed_layer, sx, sy]
            if remaining > 0:
                material_pool += remaining
                state.terrain_layers[exposed_layer, sx, sy] = 0
                state.terrain_materials[exposed_layer, sx, sy] = ""

    # Distribute any excess to sides
    if material_pool > 0:
        _distribute_to_sides(state, material_pool, left_pos, right_pos)

    # Mark changes
    state.dirty_cells.add((sx, sy))
    state.terrain_changed = True
    state.invalidate_elevation_range()
    _invalidate_cell_appearance(state, sx, sy)

    state.messages.append(f"Slope (Down): gradient origin>sel>exit created.")


def _dig_trench_slope_up_impl(state: GameState, sx: int, sy: int,
                              origin_elev: int, target_elev: int, exit_elev: int,
                              backward_pos: tuple, forward_pos: tuple,
                              left_pos: tuple, right_pos: tuple) -> None:
    """Implementation of slope up trenching mode."""
    # Remove LIMITED material from selection (keep it above origin + margin)
    exposed_layer = _find_exposed_layer(state, sx, sy)
    if exposed_layer is None:
        state.messages.append("Cannot trench bedrock.")
        return

    available = state.terrain_layers[exposed_layer, sx, sy]
    if available == 0:
        state.messages.append("No material to remove.")
        return

    # Only remove enough to keep selection at least TRENCH_SLOPE_DROP above origin
    min_target_elev = origin_elev + TRENCH_SLOPE_DROP
    max_removal = max(0, target_elev - min_target_elev)
    material_from_target = min(available, max_removal)

    if material_from_target == 0:
        state.messages.append("Selection already at minimum for upslope.")
        return

    state.terrain_layers[exposed_layer, sx, sy] -= material_from_target
    if state.terrain_layers[exposed_layer, sx, sy] == 0:
        state.terrain_materials[exposed_layer, sx, sy] = ""

    material_pool = material_from_target

    # Raise exit above selection, then distribute remainder to sides
    exit_elev = state.elevation_grid[forward_pos]
    target_elev_after = target_elev - material_from_target  # Selection after removal

    # Calculate how much needed to raise exit above selection
    needed_for_exit = max(0, target_elev_after + TRENCH_SLOPE_DROP - exit_elev)
    to_exit = min(material_pool, needed_for_exit)

    if to_exit > 0:
        layer = _get_or_create_layer(state, forward_pos[0], forward_pos[1])
        state.terrain_layers[layer, forward_pos[0], forward_pos[1]] += to_exit
        state.dirty_cells.add(forward_pos)
        material_pool -= to_exit

    # Distribute remainder to sides
    if material_pool > 0:
        _distribute_to_sides(state, material_pool, left_pos, right_pos)

    # Mark changes
    state.dirty_cells.add((sx, sy))
    state.terrain_changed = True
    state.invalidate_elevation_range()
    _invalidate_cell_appearance(state, sx, sy)

    state.messages.append(f"Slope (Up): gradient origin<sel<exit, moved {units_to_meters(material_from_target):.1f}m.")


def _distribute_to_sides(state: GameState, material_pool: int, left_pos, right_pos) -> None:
    """Helper to distribute material to perpendicular sides with elevation-awareness."""
    if material_pool <= 0:
        return

    if left_pos and right_pos:
        left_elev = state.elevation_grid[left_pos]
        right_elev = state.elevation_grid[right_pos]

        # Fill lower side first
        if left_elev < right_elev:
            deficit = right_elev - left_elev
            fill_amount = min(material_pool, deficit)
            layer = _get_or_create_layer(state, left_pos[0], left_pos[1])
            state.terrain_layers[layer, left_pos[0], left_pos[1]] += fill_amount
            state.dirty_cells.add(left_pos)
            material_pool -= fill_amount
        elif right_elev < left_elev:
            deficit = left_elev - right_elev
            fill_amount = min(material_pool, deficit)
            layer = _get_or_create_layer(state, right_pos[0], right_pos[1])
            state.terrain_layers[layer, right_pos[0], right_pos[1]] += fill_amount
            state.dirty_cells.add(right_pos)
            material_pool -= fill_amount

        # Distribute remaining evenly
        if material_pool > 0:
            half = material_pool // 2
            left_layer = _get_or_create_layer(state, left_pos[0], left_pos[1])
            right_layer = _get_or_create_layer(state, right_pos[0], right_pos[1])
            state.terrain_layers[left_layer, left_pos[0], left_pos[1]] += half
            state.terrain_layers[right_layer, right_pos[0], right_pos[1]] += (material_pool - half)
            state.dirty_cells.update([left_pos, right_pos])
    elif left_pos:
        layer = _get_or_create_layer(state, left_pos[0], left_pos[1])
        state.terrain_layers[layer, left_pos[0], left_pos[1]] += material_pool
        state.dirty_cells.add(left_pos)
    elif right_pos:
        layer = _get_or_create_layer(state, right_pos[0], right_pos[1])
        state.terrain_layers[layer, right_pos[0], right_pos[1]] += material_pool
        state.dirty_cells.add(right_pos)


def _invalidate_cell_appearance(state: GameState, sx: int, sy: int) -> None:
    """Helper to invalidate cell appearance cache (currently unused)."""
    # This function is currently a no-op; appearance caching was removed
    pass


def terrain_action(state: GameState, action: str, args: List[str]) -> None:
    """Dispatch terrain tool actions (shovel submenu)."""
    if action == "lower":
        # args[0] should be the limit layer name (e.g. "topsoil")
        limit = args[0] if args else "bedrock"
        lower_ground(state, limit)
    elif action == "raise":
        # args[0] should be the target layer name (e.g. "topsoil")
        target = args[0] if args else "topsoil"
        raise_ground(state, target)
    elif action == "trench_flat":
        dig_trench(state, "flat")
    elif action == "slope_down":
        dig_trench(state, "slope_down")
    elif action == "slope_up":
        dig_trench(state, "slope_up")
    else:
        state.messages.append(f"Unknown terrain action: {action}")


def lower_ground(state: GameState, min_layer_name: str = "bedrock") -> None:
    """Lower ground by removing material from exposed layer (array-based)."""
    sub_pos = state.get_action_target_cell()
    sx, sy = sub_pos

    # Find the topmost non-zero layer (exposed layer)
    exposed = None
    for layer in [SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION,
                  SoilLayer.SUBSOIL, SoilLayer.REGOLITH]:
        if state.terrain_layers[layer, sx, sy] > 0:
            exposed = layer
            break

    # If no soil layers remain, allow lowering bedrock if min_layer is "bedrock"
    if exposed is None:
        if min_layer_name.lower() == "bedrock":
            # Check if we've hit minimum bedrock depth
            if state.bedrock_base[sx, sy] <= MIN_BEDROCK_ELEVATION:
                state.messages.append(f"Cannot dig deeper - bedrock floor reached ({units_to_meters(MIN_BEDROCK_ELEVATION):.1f}m)")
                return

            # Lower bedrock base (permanent terrain change)
            # NOTE: Pickaxe and shovel both share the same "cannot dig" message when hitting
            # bedrock limits. Tool-specific messages will be added during tool system refactor.
            state.bedrock_base[sx, sy] = max(MIN_BEDROCK_ELEVATION, state.bedrock_base[sx, sy] - 2)
            state.invalidate_elevation_range()
            state.terrain_changed = True
            new_elev_units = state.bedrock_base[sx, sy] + np.sum(state.terrain_layers[:, sx, sy])
            new_elev = units_to_meters(new_elev_units)
            state.messages.append(f"Lowered bedrock by 0.2m. Elev: {new_elev:.2f}m")
            state.dirty_cells.add(sub_pos)
            # Terrain was modified - invalidate subsurface connectivity cache
            if state.subsurface_cache is not None:
                state.subsurface_cache.invalidate()
            return
        else:
            state.messages.append("Hit bedrock. Use pickaxe to break through.")
            return

    # Remove 2 units (0.2m) from the exposed layer
    current_depth = state.terrain_layers[exposed, sx, sy]
    removed = min(2, current_depth)
    state.terrain_layers[exposed, sx, sy] -= removed

    material_name = state.terrain_materials[exposed, sx, sy]

    # Clear material name if layer is now empty
    if state.terrain_layers[exposed, sx, sy] == 0:
        state.terrain_materials[exposed, sx, sy] = ""

    # Update visual and terrain flags
    state.dirty_cells.add(sub_pos)
    state.invalidate_elevation_range()
    state.terrain_changed = True

    # Calculate new elevation (simplified - use grid bedrock_base + layers)
    new_elev_units = state.bedrock_base[sx, sy] + np.sum(state.terrain_layers[:, sx, sy])
    new_elev = units_to_meters(new_elev_units)
    state.messages.append(f"Removed {units_to_meters(removed):.2f}m {material_name}. Elev: {new_elev:.2f}m")

    # Terrain was modified - invalidate subsurface connectivity cache
    if state.subsurface_cache is not None:
        state.subsurface_cache.invalidate()


def raise_ground(state: GameState, target_layer_name: str = "topsoil") -> None:
    """Raise ground by adding material to the exposed (topmost) layer (array-based)."""
    sub_pos = state.get_action_target_cell()
    sx, sy = sub_pos

    cost = 0
    if state.inventory.scrap > 0:
        state.inventory.scrap -= 1
        cost = 1

    # Find the topmost non-zero layer (exposed layer)
    exposed = None
    for layer in [SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION,
                  SoilLayer.SUBSOIL, SoilLayer.REGOLITH]:
        if state.terrain_layers[layer, sx, sy] > 0:
            exposed = layer
            break

    # If no soil layers exist, add to regolith (base layer)
    if exposed is None:
        exposed = SoilLayer.REGOLITH
        # Ensure material name is set for new layer
        if not state.terrain_materials[exposed, sx, sy]:
            state.terrain_materials[exposed, sx, sy] = "gravel"  # Default regolith material

    # Add 2 units (0.2m) to the exposed layer
    state.terrain_layers[exposed, sx, sy] += 2
    material_name = state.terrain_materials[exposed, sx, sy]

    # Update visual and terrain flags
    state.dirty_cells.add(sub_pos)
    state.invalidate_elevation_range()
    state.terrain_changed = True

    # Calculate new elevation (simplified - use grid bedrock_base + layers)
    new_elev_units = state.bedrock_base[sx, sy] + np.sum(state.terrain_layers[:, sx, sy])
    new_elev = units_to_meters(new_elev_units)
    state.messages.append(f"Added {material_name} to surface (cost {cost} scrap). Elev: {new_elev:.2f}m")

    # Terrain was modified - invalidate subsurface connectivity cache
    if state.subsurface_cache is not None:
        state.subsurface_cache.invalidate()
