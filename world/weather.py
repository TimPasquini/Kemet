# weather.py
"""
Weather and time-of-day system for Kemet.

Manages day/night cycle, heat, and precipitation as a cohesive subsystem.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List

from config import (
    DAY_LENGTH,
    HEAT_MIN,
    HEAT_MAX,
    RAIN_INTERVAL_MIN,
    RAIN_INTERVAL_MAX,
    RAIN_DURATION_MIN,
    RAIN_DURATION_MAX,
)


@dataclass
class WeatherSystem:
    """
    Manages day/night cycle, heat, and precipitation.

    This is a serializable dataclass for future save/load support.
    """
    day: int = 1
    turn_in_day: int = 0
    is_night: bool = False
    heat: int = 100
    rain_timer: int = 1200
    raining: bool = False

    def tick(self) -> List[str]:
        """
        Advance weather by one simulation tick.

        Returns a list of event messages to display to the player.
        """
        messages: List[str] = []

        if not self.is_night:
            self.turn_in_day += 1
            # Calculate heat based on progress through the day (peaks at midday)
            if DAY_LENGTH > 1:
                day_factor = 1 - abs((self.turn_in_day / (DAY_LENGTH - 1)) * 2 - 1)
            else:
                day_factor = 1.0
            self.heat = HEAT_MIN + int((HEAT_MAX - HEAT_MIN) * day_factor)

            if self.turn_in_day >= DAY_LENGTH:
                self.is_night = True
                self.heat = HEAT_MIN
                messages.append("Night falls. Press Space to rest.")

        # Rain logic
        self.rain_timer -= 1
        if self.raining:
            if self.rain_timer <= 0:
                self.raining = False
                self.rain_timer = random.randint(RAIN_INTERVAL_MIN, RAIN_INTERVAL_MAX)
                messages.append("Rain fades.")
        elif self.rain_timer <= 0:
            self.raining = True
            self.rain_timer = random.randint(RAIN_DURATION_MIN, RAIN_DURATION_MAX)
            messages.append("Rain arrives! Wellsprings surge.")

        return messages

    def end_day(self) -> List[str]:
        """
        End the current day and start a new one.

        Returns a list of event messages. If called during daytime,
        returns an error message without changing state.
        """
        messages: List[str] = []

        if not self.is_night:
            messages.append("Can only rest at night. Wait for day to end.")
            return messages

        self.day += 1
        self.turn_in_day = 0
        self.is_night = False
        self.heat = 100
        messages.append(f"Day {self.day} begins.")
        return messages
