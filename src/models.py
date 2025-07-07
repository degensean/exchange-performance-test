from typing import List
from dataclasses import dataclass


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
