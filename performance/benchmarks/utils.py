"""Shared utilities for performance benchmarks and profilers."""
from __future__ import annotations

import time
from typing import List, Tuple
from statistics import mean, median, stdev


class Timer:
    """Context manager for timing code blocks."""

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed = time.perf_counter() - self.start


# =============================================================================
# Statistics
# =============================================================================

def get_time_stats(times: List[float]) -> Tuple[float, float, float, float, float]:
    """Returns (mean, median, stdev, min, max) in seconds."""
    if not times:
        return (0.0, 0.0, 0.0, 0.0, 0.0)
    return (
        mean(times),
        median(times),
        stdev(times) if len(times) > 1 else 0.0,
        min(times),
        max(times)
    )


# =============================================================================
# Formatting
# =============================================================================

def format_time_ms(seconds: float) -> str:
    """Format time in milliseconds: '12.34ms'"""
    return f"{seconds * 1000:.2f}ms"


def format_time_s(seconds: float) -> str:
    """Format time in seconds: '1.23s'"""
    return f"{seconds:.2f}s"


def format_memory_mb(bytes_: int) -> str:
    """Format memory in megabytes: '123.4 MB'"""
    return f"{bytes_ / (1024 * 1024):.1f} MB"


# =============================================================================
# Report Formatting
# =============================================================================

def print_section_header(title: str, width: int = 80):
    """Print section header with border."""
    print("\n" + "=" * width)
    print(title)
    print("=" * width)


def print_metric(label: str, value: str, indent: int = 2):
    """Print formatted metric: '  Label:             value'"""
    print(f"{' ' * indent}{label:<25} {value}")


def print_table_header(columns: List[Tuple[str, int]]):
    """Print table header with column widths."""
    header = " ".join(f"{col:<width}" for col, width in columns)
    print(header)
    print("-" * len(header))


def print_table_row(values: List[str], widths: List[int]):
    """Print table row aligned to column widths."""
    row = " ".join(f"{val:<width}" for val, width in zip(values, widths))
    print(row)


# =============================================================================
# Progress
# =============================================================================

def print_progress(current: int, total: int, label: str = "Progress"):
    """Print progress bar that overwrites itself."""
    percent = (current / total) * 100 if total > 0 else 0
    print(f"    {label}: {percent:.0f}% ({current}/{total})", end='\r')


def print_progress_complete(total: int, label: str = "Progress"):
    """Print final progress message."""
    print(f"    {label}: 100% ({total}/{total})")
