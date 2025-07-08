import time
import json
import asyncio
from binance.spot import Spot
from binance.websocket.spot.websocket_stream import SpotWebsocketStreamClient
from binance.error import ClientError, ServerError
from websocket import WebSocketTimeoutException
from .base_exchange import BaseExchange, APIMode
from .config import BINANCE_CONFIG, ORDER_SIZE_BTC, MARKET_OFFSET


class BinanceExchange(BaseExchange):
    """Binance REST API implementation using official binance-connector for spot trading"""
    
    def __init__(self, api_key: str, api_secret: str, symbol: str | None = None):
        super().__init__("Binance-Spot", APIMode.REST)
        
        self.logger.info("Initializing Binance exchange for spot trading using official connector")
        
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbol = symbol or BINANCE_CONFIG['symbol']
        
        # Initialize Binance Spot client with official connector
        self.client = Spot(
            api_key=self.api_key,
            api_secret=self.api_secret,
            base_url=BINANCE_CONFIG['base_url'],
            timeout=10  # 10 second timeout
        )
        
        # WebSocket client for orderbook streaming
        self.ws_client = None
        
        self.logger.info("Binance REST client initialized successfully")
    
    def _get_tick_size(self, price: float) -> float:
        """Get tick size for BTCUSDT on Binance Spot"""
        if price >= BINANCE_CONFIG['tick_threshold']:
            return BINANCE_CONFIG['tick_size_high']
        else:
            return BINANCE_CONFIG['tick_size_low']
    
    def _round_to_tick_size(self, price: float) -> float:
        """Round price to the nearest valid tick size"""
        tick_size = self._get_tick_size(price)
        return round(price / tick_size) * tick_size
    
    def _format_quantity(self, quantity: float) -> str:
        """Format quantity with correct precision for spot trading"""
        precision = BINANCE_CONFIG['quantity_precision']
        
        # Start with precise formatting
        formatted = f"{quantity:.{precision}f}"
        
        # For spot trading, we can be flexible with trailing zeros
        formatted = formatted.rstrip('0').rstrip('.')
        
        # Final safety check
        if not formatted or formatted == '0' or float(formatted) <= 0:
            min_quantity = 10 ** (-precision)
            formatted = f"{min_quantity:.{precision}f}"
            self.logger.warning(f"Quantity {quantity} too small, using minimum: {formatted}")
        
        self.logger.debug(f"Formatted quantity {quantity} to {formatted} with precision {precision}")
        return formatted
    
    def _format_price(self, price: float) -> str:
        """Format price with correct precision for spot trading"""
        precision = BINANCE_CONFIG['price_precision']
        formatted = f"{price:.{precision}f}"
        
        # Remove trailing zeros after decimal point but keep at least the required precision
        if '.' in formatted:
            formatted = formatted.rstrip('0')
            # Ensure we maintain minimum precision (don't remove all decimal places)
            decimal_part = formatted.split('.')[1] if '.' in formatted else ''
            if len(decimal_part) < 2:  # Ensure at least 2 decimal places for prices
                formatted = f"{price:.2f}"
        
        self.logger.debug(f"Formatted price {price} to {formatted} with precision {precision}")
        return formatted
    
    async def test_order_latency(self) -> None:
        """Test Binance order placement and cancellation latency using official connector"""
        # Get current market price from ticker
        if not self.latest_price:
            try:
                ticker = self.client.ticker_price(symbol=self.symbol)
                if ticker and 'price' in ticker:
                    self.latest_price = float(ticker['price'])
                    self.logger.debug(f"Got current price from ticker: {self.latest_price}")
                else:
                    self.logger.error("Failed to get current price from ticker")
                    return
            except Exception as e:
                self.logger.error(f"Error getting current price: {e}")
                return
        
        raw_price = self.latest_price * MARKET_OFFSET  # 5% below market
        price = self._round_to_tick_size(raw_price)
        
        self.logger.debug(f"Placing order: {ORDER_SIZE_BTC} {self.symbol} at {price}")
        
        self.failure_data.place_order_total += 1
        start_time = time.time()
        
        try:
            # Format order parameters
            quantity = self._format_quantity(ORDER_SIZE_BTC)
            formatted_price = self._format_price(price)
            
            self.logger.debug(f"Order parameters: symbol={self.symbol}, "
                             f"quantity={quantity}, price={formatted_price}, "
                             f"side=BUY, type=LIMIT")
            
            # Place order using official connector
            order_response = self.client.new_order(
                symbol=self.symbol,
                side="BUY",
                type="LIMIT",
                quantity=quantity,
                price=formatted_price,
                timeInForce="GTC"
            )
            
            place_latency = time.time() - start_time
            
            # Always record total request latency
            self.latency_data.place_order_total.append(place_latency)
            
            if order_response and 'orderId' in order_response:
                # Record success-only latency
                self.latency_data.place_order.append(place_latency)
                
                order_id = str(order_response['orderId'])
                self.logger.debug(f"Order placed successfully in {place_latency:.4f}s, ID: {order_id}")
                
                self.open_orders.append({
                    'id': order_id,
                    'symbol': self.symbol,
                    'exchange': 'binance'
                })
                
                # Cancel order immediately
                await self._cancel_order(order_id)
            else:
                self.failure_data.place_order_failures += 1
                self.logger.error(f"Order placement failed: Invalid response {order_response}")
                        
        except (ClientError, ServerError) as e:
            place_latency = time.time() - start_time
            self.latency_data.place_order_total.append(place_latency)
            self.failure_data.place_order_failures += 1
            
            # Handle specific Binance API errors
            error_msg = str(e)
            
            # Extract error code from the error message if present
            if "-1111" in error_msg or "precision" in error_msg.lower():
                self.logger.error(f"PRECISION ERROR - Order placement failed: {error_msg}")
                self.logger.error(f"PRECISION ERROR - Order parameters: "
                               f"quantity={quantity}, price={formatted_price}, symbol={self.symbol}")
            elif "-2010" in error_msg or "insufficient" in error_msg.lower():
                self.logger.error(f"INSUFFICIENT FUNDS - Order placement failed: {error_msg}")
            elif "-1013" in error_msg or "filter" in error_msg.lower():
                self.logger.error(f"FILTER FAILURE - Order placement failed: {error_msg}")
            else:
                self.logger.error(f"BINANCE API ERROR - Order placement failed: {error_msg}")
        
        except (TimeoutError, WebSocketTimeoutException) as e:
            place_latency = time.time() - start_time
            self.latency_data.place_order_total.append(place_latency)
            self.failure_data.place_order_failures += 1
            self.logger.error(f"TIMEOUT ERROR - Order placement failed: {e}")
            
        except Exception as e:
            place_latency = time.time() - start_time
            self.latency_data.place_order_total.append(place_latency)
            self.failure_data.place_order_failures += 1
            
            # Handle other errors
            error_msg = str(e)
            if "precision" in error_msg.lower():
                self.logger.error(f"PRECISION ERROR - Order placement failed: {e}")
                self.logger.error(f"PRECISION ERROR - Order parameters: "
                               f"quantity={quantity}, price={formatted_price}, symbol={self.symbol}")
            else:
                self.logger.error(f"Order placement error: {e}", exc_info=True)
    
    async def _cancel_order(self, order_id: str) -> None:
        """Cancel a specific order using official connector"""
        self.failure_data.cancel_order_total += 1
        cancel_start_time = time.time()
        
        try:
            # Cancel order using official connector
            cancel_response = self.client.cancel_order(
                symbol=self.symbol,
                orderId=int(order_id)
            )
            
            cancel_latency = time.time() - cancel_start_time
            
            # Always record total cancel latency
            self.latency_data.cancel_order_total.append(cancel_latency)
            
            if cancel_response and 'orderId' in cancel_response:
                # Record success-only cancel latency
                self.latency_data.cancel_order.append(cancel_latency)
                self.open_orders = [o for o in self.open_orders if o['id'] != order_id]
                self.logger.debug(f"Order {order_id} cancelled successfully in {cancel_latency:.4f}s")
            else:
                self.failure_data.cancel_order_failures += 1
                self.logger.error(f"Order cancellation failed for {order_id}: Invalid response {cancel_response}")
                
        except (ClientError, ServerError) as e:
            cancel_latency = time.time() - cancel_start_time
            self.latency_data.cancel_order_total.append(cancel_latency)
            self.failure_data.cancel_order_failures += 1
            
            error_msg = str(e)
            if "-2011" in error_msg:  # Order not found
                self.logger.warning(f"Order {order_id} not found during cancellation: {error_msg}")
                # Remove from open orders list since it doesn't exist
                self.open_orders = [o for o in self.open_orders if o['id'] != order_id]
            else:
                self.logger.error(f"Binance API error cancelling order {order_id}: {error_msg}")
                
        except (TimeoutError, WebSocketTimeoutException) as e:
            cancel_latency = time.time() - cancel_start_time
            self.latency_data.cancel_order_total.append(cancel_latency)
            self.failure_data.cancel_order_failures += 1
            self.logger.error(f"TIMEOUT ERROR - Order cancellation failed for {order_id}: {e}")
            
        except Exception as e:
            cancel_latency = time.time() - cancel_start_time
            self.latency_data.cancel_order_total.append(cancel_latency)
            self.failure_data.cancel_order_failures += 1
            self.logger.error(f"Error cancelling order {order_id}: {e}", exc_info=True)
    
    async def cleanup_open_orders(self):
        """Cancel all open Binance orders using official connector"""
        if not self.open_orders:
            self.logger.info("No open orders to cleanup")
            return
        
        self.logger.info(f"Cleaning up {len(self.open_orders)} open orders")
        
        for order in self.open_orders[:]:
            try:
                cancel_response = self.client.cancel_order(
                    symbol=self.symbol,
                    orderId=int(order['id'])
                )
                
                if cancel_response and 'orderId' in cancel_response:
                    self.open_orders.remove(order)
                    self.logger.info(f"Successfully cancelled order {order['id']} during cleanup")
                else:
                    self.logger.warning(f"Failed to cancel order {order['id']} during cleanup: Invalid response")
                    
            except (ClientError, ServerError) as e:
                error_msg = str(e)
                if "-2011" in error_msg:  # Order not found
                    self.logger.info(f"Order {order['id']} already cancelled or filled during cleanup")
                    self.open_orders.remove(order)
                else:
                    self.logger.error(f"Binance API error during cleanup of order {order['id']}: {error_msg}")
            except Exception as e:
                self.logger.error(f"Error during cleanup of order {order['id']}: {e}", exc_info=True)
        
        if self.open_orders:
            self.logger.warning(f"Failed to cleanup {len(self.open_orders)} orders")
        else:
            self.logger.info("All orders cleaned up successfully")
    
    def __del__(self):
        """Destructor to ensure cleanup when object is garbage collected"""
        try:
            if hasattr(self, 'open_orders') and self.open_orders:
                self.logger.warning(f"BinanceExchange destructor: {len(self.open_orders)} orders still open, attempting cleanup")
                
                # Emergency synchronous cleanup
                for order in self.open_orders[:]:
                    try:
                        cancel_response = self.client.cancel_order(
                            symbol=self.symbol,
                            orderId=int(order['id'])
                        )
                        
                        if cancel_response and 'orderId' in cancel_response:
                            self.open_orders.remove(order)
                            self.logger.warning(f"Destructor cancelled order {order['id']}")
                        
                    except Exception as e:
                        error_msg = str(e)
                        if "-2011" in error_msg:  # Order not found
                            self.open_orders.remove(order)
                        else:
                            self.logger.error(f"Destructor cleanup failed for order {order['id']}: {e}")
        except Exception as e:
            # Avoid exceptions in destructor
            pass

    async def close(self):
        """Close connection and cleanup resources"""
        try:
            # Cleanup open orders first
            await self.cleanup_open_orders()
            
            # Close WebSocket if exists
            if hasattr(self, 'ws_client') and self.ws_client:
                try:
                    self.ws_client.stop()
                    self.logger.info("WebSocket connection closed")
                except Exception as e:
                    self.logger.warning(f"Error closing WebSocket: {e}")
            
            self.logger.info(f"{self.full_name} closed successfully")
            
        except Exception as e:
            self.logger.error(f"Error during close: {e}")
