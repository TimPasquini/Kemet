# Kemet – Desert Terraforming Prototype

A real-time simulation game about finding water, securing it, and greening a patch of hostile desert. This prototype validates the core gameplay loop and the underlying environmental simulation.

## Requirements
- Python 3.10+
- `pygame-ce` library

## How to Run

It is highly recommended to run the project within a Python virtual environment to manage dependencies cleanly.

Clone the repository and navigate into the project directory:

    git clone <repository_url>
    cd <repository_folder_name>

Create and activate a virtual environment:

- macOS/Linux:

    python3 -m venv venv
    source venv/bin/activate

- Windows:

    python -m venv venv
    venv\Scripts\activate

Install the required package:

    pip install pygame-ce

Run the game:

    python pygame_runner.py

## Controls (Pygame Frontend)
- **Movement:** WASD  
- **Select & Use Tool:** 1 through 9 keys  
- **Rest at Night:** SPACE  
- **Toggle Help:** H  
- **Quit Game:** ESC  

## Gameplay Goals
- Create your first green tile by growing and harvesting biomass from a planter.  
- Secure a water supply by building and filling a cistern.  
- Survive a dust front (heat spike) without losing all your stored water.  

## Simulation Highlights
- **Continuous Time:** The world operates on a continuous real-time clock. The day/night cycle, weather, and environmental physics progress independently of the player's actions.
- **Detailed Water Physics:** Water is a finite resource that flows across the surface, seeps vertically between soil layers, and builds up pressure against impermeable bedrock, creating a dynamic water table.
- **Evolving Biomes:** The landscape is not static. Based on moisture history, soil composition, and elevation, regions can transform from barren sand to fertile flats or salty pans over time.
- **Fixed-Layer Terrain:** Each grid cell has a detailed soil profile, from organics and topsoil down to bedrock. Player actions like digging or farming can directly alter this composition.
- **Dynamic Weather:** A day/night cycle affects evaporation rates, and periodic rain can provide a temporary but powerful boost to wellsprings and surface water levels.

## Performance

Kemet uses a fully vectorized NumPy-based architecture for high-performance environmental simulation:

- **Rendering**: 285 FPS average (19× better than 60 FPS target)
  - Adaptive resolution rendering scales efficiently from zoomed-in to fully zoomed-out views
  - 100% of frames render under 16.67ms even at extreme zoom levels
  - Cached background with dirty-rect updates for static terrain

- **Simulation**: ~24 TPS on 180×135 grid (41ms per tick)
  - Sub-linear scaling achieved through vectorization (27-36% better than linear)
  - All physics calculations run on NumPy arrays (water flow, erosion, evaporation, atmosphere)

- **Memory**: ~18 MB for baseline 180×135 grid (~720 bytes per cell)
  - Scales linearly with grid size

See `performance/BENCHMARK_HISTORY.md` for detailed metrics and `performance/README.md` for benchmarking tools.

