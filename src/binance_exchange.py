import time
import json
import asyncio
import aiohttp
import websockets
import hmac
import hashlib
import urllib.parse
from .base_exchange import BaseExchange
from .config import BINANCE_CONFIG, ORDER_SIZE_BTC, MARKET_OFFSET


class BinanceExchange(BaseExchange):
    """Binance exchange implementation supporting spot, UM futures, and portfolio margin"""
    
    def __init__(self, api_key: str, api_secret: str, symbol: str | None = None, account_type: str | None = None):
        self.account_type = account_type or BINANCE_CONFIG['account_type']
        
        # Validate account type
        if self.account_type not in ['spot', 'umfutures', 'portfolio']:
            raise ValueError(f"Invalid account_type: {self.account_type}. Must be 'spot', 'umfutures', or 'portfolio'")
        
        # Set display name based on account type
        display_name = f"Binance-{self.account_type.capitalize()}"
        super().__init__(display_name)
        
        self.logger.info(f"Initializing Binance exchange with account type: {self.account_type}")
        
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbol = symbol or BINANCE_CONFIG['symbol']
        
        self.base_url = BINANCE_CONFIG['base_urls'][self.account_type]
        self.ws_url = BINANCE_CONFIG['ws_urls'][self.account_type]
        self.api_endpoint = BINANCE_CONFIG['api_endpoints'][self.account_type]
        
    
    def _generate_signature(self, query_string: str) -> str:
        """Generate HMAC SHA256 signature for Binance API"""
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _get_tick_size(self, price: float) -> float:
        """Get tick size for BTCUSDT on Binance Futures"""
        if price >= BINANCE_CONFIG['tick_threshold']:
            return BINANCE_CONFIG['tick_size_high']
        else:
            return BINANCE_CONFIG['tick_size_low']
    
    def _round_to_tick_size(self, price: float) -> float:
        """Round price to the nearest valid tick size"""
        tick_size = self._get_tick_size(price)
        return round(price / tick_size) * tick_size
    
    def _format_quantity(self, quantity: float) -> str:
        """Format quantity with correct precision for the account type"""
        precision = BINANCE_CONFIG['quantity_precision'][self.account_type]
        
        # Format with exact precision first
        formatted = f"{quantity:.{precision}f}"
        
        # For quantities, we need to be more careful about trailing zeros
        # Only remove trailing zeros if we maintain at least 3 decimal places for non-spot
        if self.account_type in ['umfutures', 'portfolio']:
            # For futures/portfolio, maintain at least 3 decimal places
            if '.' in formatted:
                parts = formatted.split('.')
                decimal_part = parts[1].rstrip('0')
                if len(decimal_part) < 3:
                    # Pad back to 3 decimal places minimum
                    decimal_part = decimal_part.ljust(3, '0')
                formatted = f"{parts[0]}.{decimal_part}"
        else:
            # For spot, we can be more flexible but still maintain precision
            formatted = formatted.rstrip('0').rstrip('.')
        
        # Final safety check
        if not formatted or formatted == '0' or float(formatted) <= 0:
            min_quantity = 10 ** (-precision)
            formatted = f"{min_quantity:.{precision}f}"
            if self.account_type in ['umfutures', 'portfolio']:
                # Ensure minimum 3 decimals for futures/portfolio
                if '.' in formatted:
                    parts = formatted.split('.')
                    if len(parts[1]) < 3:
                        parts[1] = parts[1].ljust(3, '0')
                    formatted = f"{parts[0]}.{parts[1]}"
            self.logger.warning(f"Quantity {quantity} too small, using minimum: {formatted}")
        
        self.logger.debug(f"Formatted quantity {quantity} to {formatted} with precision {precision}")
        return formatted
    
    def _format_price(self, price: float) -> str:
        """Format price with correct precision for the account type"""
        precision = BINANCE_CONFIG['price_precision'][self.account_type]
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
    
    def _extract_bids_asks(self, orderbook_data):
        """Extract bids and asks from Binance orderbook data"""
        try:
            if 'b' in orderbook_data and 'a' in orderbook_data:
                return orderbook_data['b'], orderbook_data['a']
            elif 'bids' in orderbook_data and 'asks' in orderbook_data:
                return orderbook_data['bids'], orderbook_data['asks']
        except Exception:
            pass
        return None, None
    
    async def test_orderbook_latency(self) -> None:
        """Test Binance futures orderbook latency via websocket"""
        self.failure_data.orderbook_total += 1
        start_time = time.time()
        
        try:
            uri = f"{self.ws_url}{self.symbol.lower()}@depth5@100ms"
            self.logger.debug(f"Connecting to WebSocket: {uri}")
            
            async with websockets.connect(uri) as websocket:
                message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                latency = time.time() - start_time
                
                # Always record total request latency (success + failures)
                self.latency_data.orderbook_total.append(latency)
                
                data = json.loads(message)
                self.latest_orderbook = data
                
                if 'b' in data and 'a' in data:
                    # Record success-only latency
                    self.latency_data.orderbook.append(latency)
                    self.latest_price = self.get_mid_price_from_orderbook()
                    self.logger.debug(f"Orderbook retrieved successfully in {latency:.4f}s")
                else:
                    self.failure_data.orderbook_failures += 1
                    self.logger.warning(f"Invalid orderbook data structure: missing 'b' or 'a' fields")
                    
        except asyncio.TimeoutError:
            latency = time.time() - start_time
            self.latency_data.orderbook_total.append(latency)
            self.failure_data.orderbook_failures += 1
            self.logger.error(f"Orderbook request timeout after {latency:.4f}s")
        except websockets.exceptions.ConnectionClosed as e:
            latency = time.time() - start_time
            self.latency_data.orderbook_total.append(latency)
            self.failure_data.orderbook_failures += 1
            self.logger.error(f"WebSocket connection closed unexpectedly: {e}")
        except json.JSONDecodeError as e:
            latency = time.time() - start_time
            self.latency_data.orderbook_total.append(latency)
            self.failure_data.orderbook_failures += 1
            self.logger.error(f"Failed to parse JSON response: {e}")
        except Exception as e:
            latency = time.time() - start_time
            self.latency_data.orderbook_total.append(latency)
            self.failure_data.orderbook_failures += 1
            self.logger.error(f"Unexpected error in orderbook request: {e}", exc_info=True)
    
    def _get_order_params(self, price: float) -> dict:
        """Get order parameters based on account type"""
        formatted_quantity = self._format_quantity(ORDER_SIZE_BTC)
        formatted_price = self._format_price(price)
        
        base_params = {
            'symbol': self.symbol,
            'side': 'BUY',
            'type': 'LIMIT',
            'quantity': formatted_quantity,
            'price': formatted_price,
            'timestamp': int(time.time() * 1000)
        }
        
        if self.account_type == 'spot':
            base_params['timeInForce'] = 'GTC'
        elif self.account_type in ['umfutures', 'portfolio']:
            base_params['timeInForce'] = 'GTC'
            
        return base_params
    
    def _get_cancel_params(self, order_id: str) -> dict:
        """Get cancel parameters based on account type"""
        return {
            'symbol': self.symbol,
            'orderId': order_id,
            'timestamp': int(time.time() * 1000)
        }
    
    async def test_order_latency(self) -> None:
        """Test Binance order placement and cancellation latency"""
        # If we don't have latest price, fetch orderbook first
        if not self.latest_price:
            self.logger.debug("No latest price available, fetching orderbook first")
            await self.test_orderbook_latency()
            
            # Check if we got a price after fetching orderbook
            if not self.latest_price:
                self.logger.warning("Still no latest price available after fetching orderbook")
                return
        
        raw_price = self.latest_price * MARKET_OFFSET  # 5% below market
        price = self._round_to_tick_size(raw_price)
        
        self.logger.debug(f"Placing order: {ORDER_SIZE_BTC} {self.symbol} at {price}")
        
        self.failure_data.place_order_total += 1
        start_time = time.time()
        
        try:
            params = self._get_order_params(price)
            
            # Log detailed order parameters for debugging precision issues
            self.logger.debug(f"Order parameters: symbol={params['symbol']}, "
                             f"quantity={params['quantity']} (type: {type(params['quantity'])}), "
                             f"price={params['price']} (type: {type(params['price'])}), "
                             f"side={params['side']}, type={params['type']}")
            
            query_string = urllib.parse.urlencode(params)
            signature = self._generate_signature(query_string)
            params['signature'] = signature
            
            headers = {
                'X-MBX-APIKEY': self.api_key,
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}{self.api_endpoint}",
                    headers=headers,
                    data=params
                ) as response:
                    place_latency = time.time() - start_time
                    
                    # Always record total request latency
                    self.latency_data.place_order_total.append(place_latency)
                    
                    if response.status == 200:
                        order_data = await response.json()
                        # Record success-only latency
                        self.latency_data.place_order.append(place_latency)
                        
                        order_id = order_data['orderId']
                        self.logger.debug(f"Order placed successfully in {place_latency:.4f}s, ID: {order_id}")
                        
                        self.open_orders.append({
                            'id': order_id,
                            'symbol': self.symbol,
                            'exchange': 'binance'
                        })
                        
                        # Cancel order
                        await self._cancel_order(session, headers, order_id)
                    else:
                        self.failure_data.place_order_failures += 1
                        error_text = await response.text()
                        
                        # Special handling for precision errors
                        if '"code":-1111' in error_text:
                            self.logger.error(f"PRECISION ERROR - Order placement failed with status {response.status}: {error_text}")
                            self.logger.error(f"PRECISION ERROR - Order parameters that caused error: "
                                            f"quantity='{params['quantity']}', price='{params['price']}', "
                                            f"symbol={params['symbol']}, account_type={self.account_type}")
                        else:
                            self.logger.error(f"Order placement failed with status {response.status}: {error_text}")
                        
        except aiohttp.ClientError as e:
            place_latency = time.time() - start_time
            self.latency_data.place_order_total.append(place_latency)
            self.failure_data.place_order_failures += 1
            self.logger.error(f"HTTP client error during order placement: {e}")
        except asyncio.TimeoutError:
            place_latency = time.time() - start_time
            self.latency_data.place_order_total.append(place_latency)
            self.failure_data.place_order_failures += 1
            self.logger.error(f"Order placement timeout after {place_latency:.4f}s")
        except Exception as e:
            place_latency = time.time() - start_time
            self.latency_data.place_order_total.append(place_latency)
            self.failure_data.place_order_failures += 1
            self.logger.error(f"Unexpected error during order placement: {e}", exc_info=True)
    
    async def _cancel_order(self, session: aiohttp.ClientSession, headers: dict, order_id: str) -> None:
        """Cancel a specific order and log the result"""
        self.failure_data.cancel_order_total += 1
        cancel_params = self._get_cancel_params(order_id)
        
        cancel_query = urllib.parse.urlencode(cancel_params)
        cancel_signature = self._generate_signature(cancel_query)
        cancel_params['signature'] = cancel_signature
        
        cancel_start_time = time.time()
        
        try:
            async with session.delete(
                f"{self.base_url}{self.api_endpoint}",
                headers=headers,
                data=cancel_params
            ) as cancel_response:
                cancel_latency = time.time() - cancel_start_time
                
                # Always record total cancel latency
                self.latency_data.cancel_order_total.append(cancel_latency)
                
                if cancel_response.status == 200:
                    # Record success-only cancel latency
                    self.latency_data.cancel_order.append(cancel_latency)
                    self.open_orders = [o for o in self.open_orders if o['id'] != order_id]
                    self.logger.debug(f"Order {order_id} cancelled successfully in {cancel_latency:.4f}s")
                else:
                    self.failure_data.cancel_order_failures += 1
                    error_text = await cancel_response.text()
                    self.logger.error(f"Order cancellation failed for {order_id} with status {cancel_response.status}: {error_text}")
        except Exception as e:
            cancel_latency = time.time() - cancel_start_time
            self.latency_data.cancel_order_total.append(cancel_latency)
            self.failure_data.cancel_order_failures += 1
            self.logger.error(f"Error cancelling order {order_id}: {e}", exc_info=True)
    
    async def cleanup_open_orders(self):
        """Cancel all open Binance orders"""
        if not self.open_orders:
            self.logger.info("No open orders to cleanup")
            return
        
        self.logger.info(f"Cleaning up {len(self.open_orders)} open orders")
        
        headers = {
            'X-MBX-APIKEY': self.api_key,
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        async with aiohttp.ClientSession() as session:
            for order in self.open_orders[:]:
                try:
                    cancel_params = self._get_cancel_params(order['id'])
                    
                    cancel_query = urllib.parse.urlencode(cancel_params)
                    cancel_signature = self._generate_signature(cancel_query)
                    cancel_params['signature'] = cancel_signature
                    
                    async with session.delete(
                        f"{self.base_url}{self.api_endpoint}",
                        headers=headers,
                        data=cancel_params
                    ) as cancel_response:
                        if cancel_response.status == 200:
                            self.open_orders.remove(order)
                            self.logger.info(f"Successfully cancelled order {order['id']} during cleanup")
                        else:
                            error_text = await cancel_response.text()
                            self.logger.warning(f"Failed to cancel order {order['id']} during cleanup: {error_text}")
                            
                except Exception as e:
                    self.logger.error(f"Error during cleanup of order {order['id']}: {e}", exc_info=True)
        
        if self.open_orders:
            self.logger.warning(f"Failed to cleanup {len(self.open_orders)} orders")
        else:
            self.logger.info("All orders cleaned up successfully")
