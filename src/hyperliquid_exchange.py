import time
import eth_account
from eth_account.signers.local import LocalAccount
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from .base_exchange import BaseExchange
from .config import HYPERLIQUID_CONFIG, ORDER_SIZE_BTC, MARKET_OFFSET


class HyperliquidExchange(BaseExchange):
    """Hyperliquid exchange implementation"""
    
    def __init__(self, wallet_address: str, private_key: str, asset: str | None = None):
        super().__init__("Hyperliquid")
        
        self.logger.info("Initializing Hyperliquid exchange")
        
        self.wallet_address = wallet_address
        self.private_key = private_key
        self.asset = asset or HYPERLIQUID_CONFIG['asset']
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        
        # Create LocalAccount for signing
        self.account: LocalAccount = eth_account.Account.from_key(private_key)
        self.exchange = Exchange(self.account, constants.MAINNET_API_URL, account_address=wallet_address)
        
        self.logger.info(f"Hyperliquid exchange initialized for wallet: {wallet_address}, asset: {self.asset}")

    def _get_tick_size(self, asset: str = "BTC") -> float:
        """Get the correct tick size for Hyperliquid assets"""
        if asset == "BTC":
            return HYPERLIQUID_CONFIG['tick_size']
        return HYPERLIQUID_CONFIG['default_tick_size']

    def _round_to_tick_size(self, price: float, asset: str = "BTC") -> float:
        """Round price to the nearest valid tick size"""
        tick_size = self._get_tick_size(asset)
        return round(price / tick_size) * tick_size

    def _extract_bids_asks(self, orderbook_data):
        """Extract bids and asks from Hyperliquid orderbook data"""
        try:
            if isinstance(orderbook_data, dict) and 'levels' in orderbook_data:
                levels = orderbook_data['levels']
                if isinstance(levels, list) and len(levels) == 2:
                    bids_data, asks_data = levels[0], levels[1]
                    
                    bids = []
                    asks = []
                    
                    for bid in bids_data:
                        if isinstance(bid, dict) and 'px' in bid and 'sz' in bid:
                            bids.append([bid['px'], bid['sz']])
                    
                    for ask in asks_data:
                        if isinstance(ask, dict) and 'px' in ask and 'sz' in ask:
                            asks.append([ask['px'], ask['sz']])
                    
                    self.logger.debug(f"Extracted {len(bids)} bids and {len(asks)} asks from orderbook")
                    return bids, asks
                else:
                    self.logger.warning(f"Invalid levels structure: expected list of length 2, got {type(levels)} with length {len(levels) if isinstance(levels, list) else 'N/A'}")
            else:
                self.logger.warning(f"Invalid orderbook data: expected dict with 'levels' key, got {type(orderbook_data)} with keys {list(orderbook_data.keys()) if isinstance(orderbook_data, dict) else 'N/A'}")
        except Exception as e:
            self.logger.error(f"Error extracting bids/asks: {e}", exc_info=True)
        return None, None

    async def test_orderbook_latency(self) -> None:
        """Test Hyperliquid orderbook latency"""
        self.failure_data.orderbook_total += 1
        start_time = time.time()
        
        try:
            self.logger.debug(f"Fetching L2 orderbook for {self.asset}")
            l2_data = self.info.l2_snapshot(self.asset)
            latency = time.time() - start_time
            
            # Always record total request latency (success + failures)
            self.latency_data.orderbook_total.append(latency)
            
            if l2_data:
                # Record success-only latency
                self.latency_data.orderbook.append(latency)
                self.latest_orderbook = l2_data
                self.latest_price = self.get_mid_price_from_orderbook()
                self.logger.debug(f"Orderbook retrieved successfully in {latency:.4f}s")
            else:
                self.failure_data.orderbook_failures += 1
                self.logger.warning("Received empty orderbook data from Hyperliquid")
                
        except Exception as e:
            latency = time.time() - start_time
            # Record total request latency even for exceptions
            self.latency_data.orderbook_total.append(latency)
            self.failure_data.orderbook_failures += 1
            self.logger.error(f"Orderbook request failed: {e}", exc_info=True)
    
    async def test_order_latency(self) -> None:
        """Test Hyperliquid order placement and cancellation latency"""
        if not self.exchange:
            self.logger.warning("No exchange available for order test")
            return
            
        # If we don't have latest price, fetch orderbook first
        if not self.latest_price:
            self.logger.debug("No latest price available, fetching orderbook first")
            await self.test_orderbook_latency()
            
            # Check if we got a price after fetching orderbook
            if not self.latest_price:
                self.logger.warning("Still no latest price available after fetching orderbook")
                return
        
        # Place order 5% below market to avoid execution
        raw_price = self.latest_price * MARKET_OFFSET
        price = self._round_to_tick_size(raw_price, self.asset)
        
        self.logger.debug(f"Placing order: {ORDER_SIZE_BTC} {self.asset} at {price}")
        
        self.failure_data.place_order_total += 1
        start_time = time.time()
        
        try:
            # Place order
            result = self.exchange.order(
                name=self.asset,
                is_buy=True,
                sz=ORDER_SIZE_BTC,
                limit_px=price,
                order_type={"limit": {"tif": "Gtc"}},
                reduce_only=False
            )
            place_latency = time.time() - start_time
            
            # Always record total request latency
            self.latency_data.place_order_total.append(place_latency)
            
            if result and result.get("status") == "ok":
                # Record success-only latency
                self.latency_data.place_order.append(place_latency)
                
                self.logger.debug(f"Order placed successfully in {place_latency:.4f}s")
                
                # Try to cancel order immediately
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                if statuses and "resting" in statuses[0]:
                    order_id = statuses[0]["resting"]["oid"]
                    
                    # Track for cleanup
                    self.open_orders.append({
                        'id': order_id,
                        'asset': self.asset,
                        'exchange': 'hyperliquid'
                    })
                    
                    # Cancel order
                    await self._cancel_order(order_id)
                else:
                    self.failure_data.place_order_failures += 1
                    self.logger.warning("Order status not resting, cannot cancel")
            else:
                self.failure_data.place_order_failures += 1
                error_msg = result.get("error", "Unknown error") if result else "No result returned"
                self.logger.error(f"Order placement failed: {error_msg}")
            
        except Exception as e:
            place_latency = time.time() - start_time
            # Record total request latency even for exceptions
            self.latency_data.place_order_total.append(place_latency)
            self.failure_data.place_order_failures += 1
            self.logger.error(f"Unexpected error during order placement: {e}", exc_info=True)
    
    async def _cancel_order(self, order_id: str) -> None:
        """Cancel a specific order and log the result"""
        self.failure_data.cancel_order_total += 1
        cancel_start_time = time.time()
        
        try:
            cancel_result = self.exchange.cancel(self.asset, int(order_id))
            cancel_latency = time.time() - cancel_start_time
            
            # Always record total cancel latency
            self.latency_data.cancel_order_total.append(cancel_latency)
            
            if cancel_result and cancel_result.get("status") == "ok":
                # Record success-only cancel latency
                self.latency_data.cancel_order.append(cancel_latency)
                self.open_orders = [o for o in self.open_orders if o['id'] != order_id]
                self.logger.debug(f"Order {order_id} cancelled successfully in {cancel_latency:.4f}s")
            else:
                self.failure_data.cancel_order_failures += 1
                error_msg = cancel_result.get("error", "Unknown error") if cancel_result else "No result returned"
                self.logger.error(f"Order cancellation failed for {order_id}: {error_msg}")
                
        except Exception as e:
            cancel_latency = time.time() - cancel_start_time
            self.latency_data.cancel_order_total.append(cancel_latency)
            self.failure_data.cancel_order_failures += 1
            self.logger.error(f"Error cancelling order {order_id}: {e}", exc_info=True)
    
    async def cleanup_open_orders(self):
        """Cancel all open Hyperliquid orders"""
        if not self.open_orders:
            self.logger.info("No open orders to cleanup")
            return
        
        self.logger.info(f"Cleaning up {len(self.open_orders)} open orders")
        
        for order in self.open_orders[:]:
            try:
                result = self.exchange.cancel(order['asset'], int(order['id']))
                if result and result.get("status") == "ok":
                    self.open_orders.remove(order)
                    self.logger.info(f"Successfully cancelled order {order['id']} during cleanup")
                else:
                    error_msg = result.get("error", "Unknown error") if result else "No result returned"
                    self.logger.warning(f"Failed to cancel order {order['id']} during cleanup: {error_msg}")
            except Exception as e:
                self.logger.error(f"Error during cleanup of order {order['id']}: {e}", exc_info=True)
        
        if self.open_orders:
            self.logger.warning(f"Failed to cleanup {len(self.open_orders)} orders")
        else:
            self.logger.info("All orders cleaned up successfully")
