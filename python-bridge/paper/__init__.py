"""Paper-trading adapters that convert strategy targets into simulation orders."""

from .smallcap import SmallCapPaperConfig, SmallCapRebalancePlan, build_smallcap_rebalance_plan

__all__ = [
    "SmallCapPaperConfig",
    "SmallCapRebalancePlan",
    "build_smallcap_rebalance_plan",
]
