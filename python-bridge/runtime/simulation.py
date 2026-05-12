from __future__ import annotations

from execution.simulation import SimulationExecution
from strategy.base import BaseStrategy

from .base import BaseRuntime


class SimulationRuntime(BaseRuntime):
    """Runtime for real-time ticks flowing into the local simulation execution."""

    def __init__(self, strategy: BaseStrategy, execution: SimulationExecution | None = None) -> None:
        super().__init__(strategy, execution or SimulationExecution())
