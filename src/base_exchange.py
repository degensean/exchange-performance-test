from typing import Optional
from .models import LatencyData, FailureData
from .logger import get_logger


class BaseExchange:
    """Base class for exchange implementations"""
    
    def __init__(self, name: str):
        self.name = name
        self.latency_data = LatencyData()
        self.failure_data = FailureData()
        self.latest_orderbook = None  # Store latest orderbook data
        self.latest_price = None      # Store latest mid price from orderbook
        self.open_orders = []         # Track open orders for cleanup
        self.logger = get_logger(f"exchange.{name.lower()}")
        
    
    async def test_orderbook_latency(self) -> None:
        """Test orderbook retrieval latency"""
        raise NotImplementedError
    
    async def test_order_latency(self) -> None:
        """Test order placement and cancellation latency"""
        raise NotImplementedError
    
    def get_mid_price_from_orderbook(self) -> Optional[float]:
        """Get mid price from latest orderbook data"""
        if not self.latest_orderbook:
            self.logger.debug("No orderbook data available for mid price calculation")
            return None
        
        try:
            # Extract best bid and ask from orderbook
            bids, asks = self._extract_bids_asks(self.latest_orderbook)
            self.logger.debug(f"Extracted bids: {bids is not None}, asks: {asks is not None}")
            if bids and asks:
                best_bid = float(bids[0][0])  # First bid price
                best_ask = float(asks[0][0])  # First ask price
                mid_price = (best_bid + best_ask) / 2
                self.logger.debug(f"Calculated mid price: {mid_price} (bid: {best_bid}, ask: {best_ask})")
                return mid_price
            else:
                self.logger.warning("No bids or asks available in orderbook data")
        except Exception as e:
            self.logger.error(f"Error calculating mid price: {e}", exc_info=True)
        return None
    
    def _extract_bids_asks(self, orderbook_data):
        """Extract bids and asks from orderbook data - to be implemented by subclasses"""
        raise NotImplementedError
    
    async def cleanup_open_orders(self):
        """Cancel all open orders - to be implemented by subclasses"""
        raise NotImplementedError
