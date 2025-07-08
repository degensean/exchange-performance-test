from typing import Optional
from enum import Enum
from .models import LatencyData, FailureData
from .logger import get_logger


class APIMode(Enum):
    """API communication modes"""
    REST = "rest"
    WEBSOCKET = "websocket"


class BaseExchange:
    """Base class for exchange implementations"""
    
    def __init__(self, name: str, api_mode: APIMode = APIMode.REST):
        self.name = name
        self.api_mode = api_mode
        self.full_name = f"{name}-{api_mode.value.upper()}"
        self.latency_data = LatencyData()
        self.failure_data = FailureData()
        self.latest_price = None      # Store latest price for order placement
        self.open_orders = []         # Track open orders for cleanup
        self.logger = get_logger(f"exchange.{name.lower()}-{api_mode.value}")
        
    
    async def test_order_latency(self) -> None:
        """Test order placement and cancellation latency"""
        raise NotImplementedError
    
    async def cleanup_open_orders(self):
        """Cancel all open orders - to be implemented by subclasses"""
        raise NotImplementedError
