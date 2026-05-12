"""Runtime abstractions shared by backtest and simulation runners."""

from .base import BaseRuntime, ExecutionAdapter, RuntimeResult
from .simulation import SimulationRuntime

__all__ = ["BaseRuntime", "ExecutionAdapter", "RuntimeResult", "SimulationRuntime"]
