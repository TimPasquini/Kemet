# Kemet – Desert Farm Prototype (MVP)

A minimal turn-based, ASCII prototype to validate the core loop of finding water, securing it, and greening a patch in a hostile desert.

## Requirements

- Python 3.10+
- For the pygame frontend: `pip install pygame-ce`

## How to run

```powershell
cd C:\Games\Kemet
python main.py
```

### Pygame-CE frontend (20x15 map, smooth movement)

```powershell
cd C:\Games\Kemet
pip install pygame-ce
python pygame_runner.py
```

## Controls (type commands, then press Enter)

- `w a s d` — move.
- `dig` — dig a trench on your tile (improves flow, lowers evap).
- `lower` — lower ground elevation.
- `raise` — raise ground elevation (costs 1 scrap).
- `build cistern` — build a cistern on your tile (stores/retains water).
- `build condenser` — build a condenser on your tile (drips water each turn).
- `build planter` — build a planter on your tile (grows biomass if hydrated).
- `collect` — collect up to 1 water from a wet tile into inventory.
- `pour <amount>` — pour water from inventory onto your tile (e.g. `pour 1`).
- `survey` — inspect tile type/elevation/hydration.
- `status` — show inventory/resources.
- `end` — end the day (advances several ticks and raises heat).

### Notes on water and testing aids

- Water only originates at wells/springs (wadi tiles) with varying flow rates; rain is occasional and boosts those sources.
- A depot tile at spawn provides infinite test resources when using `collect`.
- `help` — list commands.
- `quit` — exit.

## Goals in this prototype

- Create your first green tile (biomass from a planter).
- Fill a cistern.
- Survive a dust front (heat spike) without losing all stored water.

## Simulation highlights

- **Hydration**: tiles track hydration; evaporation scales with daytime heat and biome. Trenches improve flow; cisterns and wadis reduce losses.
- **Flow**: wet tiles bleed some water to orthogonal neighbors each tick; trenches amplify flow.
- **Buildings**: condensers drip water, cisterns store and slow loss, planters produce biomass when hydrated.
- **Events**: day/night heat cycle; periodic dust fronts spike evaporation and damage buildings.

## Map generation (WFC-lite)

- 10x10 grid built from tile sets (dune, flat, wadi, rock, salt pan) using adjacency preferences to form plausible bands and wadis, then seeds 2–3 hidden water pockets.

## Next steps after MVP

- Add nomad trader spawn on first green patch.
- Expand tech tree (pumps, berms/swales, shade cloth).
- Add save/load, better art, and a real-time rendering layer.
