import time
import asyncio
import eth_account
from eth_account.signers.local import LocalAccount
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from hyperliquid.utils.types import L2BookMsg
from .base_exchange import BaseExchange, APIMode
from .config import HYPERLIQUID_CONFIG, ORDER_SIZE_BTC, MARKET_OFFSET


class HyperliquidWebSocketExchange(BaseExchange):
    """Hyperliquid WebSocket API implementation with WebSocket market data and optimized order operations
    
    Since Hyperliquid doesn't support true WebSocket order placement, this implementation:
    - Uses WebSocket for real-time market data (orderbook updates)
    - Uses direct SDK calls for order operations (same as REST, but in async context)
    - Provides the same interface as true WebSocket exchanges
    """
    
    def __init__(self, wallet_address: str, private_key: str, asset: str | None = None):
        super().__init__("Hyperliquid", APIMode.WEBSOCKET)
        
        self.logger.info("Initializing Hyperliquid WebSocket exchange")
        
        self.wallet_address = wallet_address
        self.private_key = private_key
        self.asset = asset or HYPERLIQUID_CONFIG['asset']
        
        # WebSocket connection state
        self.is_connected = False
        self.subscription_id = None
        self.latest_orderbook_received = asyncio.Event()
        self.orderbook_start_time = None
        
        # Create LocalAccount for signing
        self.account: LocalAccount = eth_account.Account.from_key(private_key)
        
        # Initialize Info API with WebSocket support
        self.info = Info(constants.MAINNET_API_URL, skip_ws=False)
        
        # Initialize Exchange API for WebSocket-style order operations
        self.exchange = Exchange(self.account, constants.MAINNET_API_URL, account_address=wallet_address)

    async def connect(self):
        """Establish WebSocket connection using the SDK for market data"""
        try:
            self.logger.info("Connecting to Hyperliquid WebSocket via SDK")
            
            # Subscribe to orderbook updates using the SDK
            subscription = {"type": "l2Book", "coin": self.asset}
            self.subscription_id = self.info.subscribe(subscription, self._on_orderbook_update)  # type: ignore
            
            # Note: Order operations use the Exchange SDK in an async/threaded manner
            # to simulate WebSocket-style behavior
            
            self.is_connected = True
            self.logger.info("Hyperliquid WebSocket connection established via SDK")
            
        except Exception as e:
            self.logger.error(f"Failed to connect to Hyperliquid WebSocket: {e}", exc_info=True)
            self.is_connected = False

    async def disconnect(self):
        """Close WebSocket connection"""
        try:
            if self.subscription_id is not None:
                subscription = {"type": "l2Book", "coin": self.asset}
                self.info.unsubscribe(subscription, self.subscription_id)  # type: ignore
                self.subscription_id = None
                
            # Force disconnect WebSocket with timeout
            await asyncio.wait_for(asyncio.to_thread(self.info.disconnect_websocket), timeout=5.0)
            self.is_connected = False
            self.logger.info("Hyperliquid WebSocket connection closed")
        except asyncio.TimeoutError:
            self.logger.warning("Timeout disconnecting from Hyperliquid WebSocket - forcing close")
            self.is_connected = False
        except Exception as e:
            self.logger.error(f"Error disconnecting from WebSocket: {e}", exc_info=True)
            self.is_connected = False

    def _on_orderbook_update(self, msg: L2BookMsg) -> None:
        """Callback for orderbook updates from WebSocket"""
        try:
            if msg["channel"] == "l2Book" and "data" in msg:
                orderbook_data = msg["data"]
                if orderbook_data["coin"] == self.asset:
                    self.latest_orderbook_received.set()
                    self.logger.debug(f"Received orderbook update for {self.asset}")
        except Exception as e:
            self.logger.error(f"Error processing orderbook update: {e}", exc_info=True)

    def _get_tick_size(self, asset: str = "BTC") -> float:
        """Get the correct tick size for Hyperliquid assets"""
        if asset == "BTC":
            return HYPERLIQUID_CONFIG['tick_size']
        return HYPERLIQUID_CONFIG['default_tick_size']

    def _round_to_tick_size(self, price: float, asset: str = "BTC") -> float:
        """Round price to the nearest valid tick size"""
        tick_size = self._get_tick_size(asset)
        return round(price / tick_size) * tick_size

    async def test_order_latency(self) -> None:
        """Test order placement via WebSocket-style (using Exchange SDK with async interface)"""
        
        if not self.latest_price:
            # Get current price directly from info API
            try:
                self.logger.debug(f"Getting current price for {self.asset}")
                # Get the current market price
                meta = self.info.meta()
                universe = meta.get('universe', [])
                
                for token_info in universe:
                    if token_info.get('name') == self.asset:
                        # Get the mark price (current market price)
                        all_mids = self.info.all_mids()
                        if self.asset in all_mids:
                            self.latest_price = float(all_mids[self.asset])
                            self.logger.debug(f"Got current price for {self.asset}: {self.latest_price}")
                            break
                
                if not self.latest_price:
                    self.logger.error(f"Failed to get current price for {self.asset}")
                    return
                    
            except Exception as e:
                self.logger.error(f"Error getting current price: {e}")
                return
        
        # Place order 5% below market to avoid execution
        raw_price = self.latest_price * MARKET_OFFSET
        price = self._round_to_tick_size(raw_price, self.asset)
        
        self.logger.debug(f"Placing order via WebSocket-style: {ORDER_SIZE_BTC} {self.asset} at {price}")
        
        self.failure_data.place_order_total += 1
        start_time = time.time()
        
        try:
            # Direct SDK call - same as REST but in async context
            # Note: Since Hyperliquid doesn't support true WebSocket orders,
            # we use the SDK directly for optimal performance
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
                
                self.logger.debug(f"Hyperliquid WebSocket-style order placed successfully in {place_latency:.4f}s")
                
                # Try to cancel order immediately if it's resting
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                if statuses and "resting" in statuses[0]:
                    order_id = statuses[0]["resting"]["oid"]
                    
                    # Track for cleanup
                    self.open_orders.append({
                        'id': order_id,
                        'asset': self.asset,
                        'exchange': 'hyperliquid-websocket'
                    })
                    
                    # Cancel order via WebSocket-style
                    await self._cancel_order_websocket(order_id)
                else:
                    self.failure_data.place_order_failures += 1
                    self.logger.warning("Order status not resting, cannot cancel")
            else:
                self.failure_data.place_order_failures += 1
                error_msg = result.get("error", "Unknown error") if result else "No result returned"
                self.logger.error(f"Hyperliquid WebSocket-style order placement failed: {error_msg}")
            
        except Exception as e:
            place_latency = time.time() - start_time
            # Record total request latency even for exceptions
            self.latency_data.place_order_total.append(place_latency)
            self.failure_data.place_order_failures += 1
            self.logger.error(f"Unexpected error during Hyperliquid WebSocket-style order placement: {e}", exc_info=True)

    async def _cancel_order_websocket(self, order_id: str) -> None:
        """Cancel a specific order via WebSocket-style and log the result"""
        self.failure_data.cancel_order_total += 1
        cancel_start_time = time.time()
        
        try:
            # Direct SDK call - same as REST but in async context
            # Note: Since Hyperliquid doesn't support true WebSocket orders,
            # we use the SDK directly for optimal performance
            cancel_result = self.exchange.cancel(
                self.asset,
                int(order_id)
            )
            
            cancel_latency = time.time() - cancel_start_time
            
            # Always record total cancel latency
            self.latency_data.cancel_order_total.append(cancel_latency)
            
            if cancel_result and cancel_result.get("status") == "ok":
                # Record success-only cancel latency
                self.latency_data.cancel_order.append(cancel_latency)
                self.open_orders = [o for o in self.open_orders if o['id'] != order_id]
                self.logger.debug(f"Hyperliquid WebSocket-style order {order_id} cancelled successfully in {cancel_latency:.4f}s")
            else:
                self.failure_data.cancel_order_failures += 1
                error_msg = cancel_result.get("error", "Unknown error") if cancel_result else "No result returned"
                self.logger.error(f"Hyperliquid WebSocket-style order cancellation failed for {order_id}: {error_msg}")
                
        except Exception as e:
            cancel_latency = time.time() - cancel_start_time
            self.latency_data.cancel_order_total.append(cancel_latency)
            self.failure_data.cancel_order_failures += 1
            self.logger.error(f"Error cancelling Hyperliquid WebSocket-style order {order_id}: {e}", exc_info=True)

    async def cleanup_open_orders(self):
        """Cancel all open Hyperliquid orders"""
        if not self.open_orders:
            self.logger.info("No open orders to cleanup")
            await self.disconnect()
            return
        
        self.logger.info(f"Cleaning up {len(self.open_orders)} open Hyperliquid orders")
        
        for order in self.open_orders[:]:
            try:
                result = self.exchange.cancel(order['asset'], int(order['id']))
                if result and result.get("status") == "ok":
                    self.open_orders.remove(order)
                    self.logger.info(f"Successfully cancelled Hyperliquid order {order['id']} during cleanup")
                else:
                    error_msg = result.get("error", "Unknown error") if result else "No result returned"
                    self.logger.warning(f"Failed to cancel Hyperliquid order {order['id']} during cleanup: {error_msg}")
            except Exception as e:
                self.logger.error(f"Error during cleanup of Hyperliquid order {order['id']}: {e}", exc_info=True)
        
        await self.disconnect()
        
        if self.open_orders:
            self.logger.warning(f"Failed to cleanup {len(self.open_orders)} Hyperliquid orders")
        else:
            self.logger.info("All Hyperliquid orders cleaned up successfully")

    async def close(self):
        """Close connection and cleanup resources"""
        try:
            # Cleanup open orders first with timeout
            await asyncio.wait_for(self.cleanup_open_orders(), timeout=15.0)
            
            self.logger.info(f"{self.full_name} closed successfully")
            
        except asyncio.TimeoutError:
            self.logger.error(f"Timeout during {self.full_name} close operation")
            # Force disconnect
            try:
                await asyncio.wait_for(self.disconnect(), timeout=5.0)
            except:
                pass
        except Exception as e:
            self.logger.error(f"Error during close: {e}")
            # Still try to disconnect
            try:
                await asyncio.wait_for(self.disconnect(), timeout=5.0)
            except:
                pass
