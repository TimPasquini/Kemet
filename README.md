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

