from typing import List
from dataclasses import dataclass, field


@dataclass
class FailureData:
    """Data class to store failure/error statistics"""
    place_order_failures: int = 0
    cancel_order_failures: int = 0
    place_order_total: int = 0
    cancel_order_total: int = 0
    
    def get_place_order_failure_rate(self) -> float:
        """Get order placement failure rate as percentage"""
        return (self.place_order_failures / max(self.place_order_total, 1)) * 100
    
    def get_cancel_order_failure_rate(self) -> float:
        """Get order cancellation failure rate as percentage"""
        return (self.cancel_order_failures / max(self.cancel_order_total, 1)) * 100


@dataclass
class LatencyData:
    """Data class to store latency measurements"""
    # Success-only latencies (current behavior)
    place_order: List[float] = field(default_factory=list)
    cancel_order: List[float] = field(default_factory=list)
    
    # Total request latencies (including failures)
    place_order_total: List[float] = field(default_factory=list)
    cancel_order_total: List[float] = field(default_factory=list)
