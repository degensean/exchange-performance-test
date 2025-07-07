from typing import List
from dataclasses import dataclass


@dataclass
class FailureData:
    """Data class to store failure/error statistics"""
    orderbook_failures: int = 0
    place_order_failures: int = 0
    cancel_order_failures: int = 0
    orderbook_total: int = 0
    place_order_total: int = 0
    cancel_order_total: int = 0
    
    def get_orderbook_failure_rate(self) -> float:
        """Get orderbook failure rate as percentage"""
        return (self.orderbook_failures / max(self.orderbook_total, 1)) * 100
    
    def get_place_order_failure_rate(self) -> float:
        """Get order placement failure rate as percentage"""
        return (self.place_order_failures / max(self.place_order_total, 1)) * 100
    
    def get_cancel_order_failure_rate(self) -> float:
        """Get order cancellation failure rate as percentage"""
        return (self.cancel_order_failures / max(self.cancel_order_total, 1)) * 100


@dataclass
class LatencyData:
    """Data class to store latency measurements"""
    orderbook: List[float]
    place_order: List[float] 
    cancel_order: List[float]
    
    def __post_init__(self):
        if not isinstance(self.orderbook, list):
            self.orderbook = []
        if not isinstance(self.place_order, list):
            self.place_order = []
        if not isinstance(self.cancel_order, list):
            self.cancel_order = []
