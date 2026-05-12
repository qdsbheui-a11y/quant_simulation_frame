"""Execution adapters for unified strategies."""

from .base import Execution
from .simulation_execution import SimulationExecution

__all__ = ["Execution", "SimulationExecution"]
