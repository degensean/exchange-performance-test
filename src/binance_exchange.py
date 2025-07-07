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
    """Binance futures exchange implementation using direct WebSocket API"""
    
    def __init__(self, api_key: str, api_secret: str, symbol: str | None = None):
        super().__init__("Binance")
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbol = symbol or BINANCE_CONFIG['symbol']
        self.base_url_pm = BINANCE_CONFIG['base_url']
        self.ws_url = BINANCE_CONFIG['ws_url']
    
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
                else:
                    self.failure_data.orderbook_failures += 1
                    
        except Exception:
            latency = time.time() - start_time
            # Record total request latency even for exceptions
            self.latency_data.orderbook_total.append(latency)
            self.failure_data.orderbook_failures += 1
    
    async def test_order_latency(self) -> None:
        """Test Binance futures order placement and cancellation latency"""
        if not self.latest_price:
            return
        
        raw_price = self.latest_price * MARKET_OFFSET  # 5% below market
        price = self._round_to_tick_size(raw_price)
        
        self.failure_data.place_order_total += 1
        start_time = time.time()
        try:
            timestamp = int(time.time() * 1000)
            params = {
                'symbol': self.symbol,
                'side': 'BUY',
                'type': 'LIMIT',
                'timeInForce': 'GTC',
                'quantity': str(ORDER_SIZE_BTC),
                'price': str(price),
                'timestamp': timestamp
            }
            
            query_string = urllib.parse.urlencode(params)
            signature = self._generate_signature(query_string)
            params['signature'] = signature
            
            headers = {
                'X-MBX-APIKEY': self.api_key,
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url_pm}/papi/v1/um/order",
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
                        self.open_orders.append({
                            'id': order_id,
                            'symbol': self.symbol,
                            'exchange': 'binance'
                        })
                        
                        # Cancel order
                        self.failure_data.cancel_order_total += 1
                        cancel_params = {
                            'symbol': self.symbol,
                            'orderId': order_id,
                            'timestamp': int(time.time() * 1000)
                        }
                        
                        cancel_query = urllib.parse.urlencode(cancel_params)
                        cancel_signature = self._generate_signature(cancel_query)
                        cancel_params['signature'] = cancel_signature
                        
                        cancel_start_time = time.time()
                        async with session.delete(
                            f"{self.base_url_pm}/papi/v1/um/order",
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
                            else:
                                self.failure_data.cancel_order_failures += 1
                    else:
                        self.failure_data.place_order_failures += 1
                        
        except Exception:
            place_latency = time.time() - start_time
            # Record total request latency even for exceptions
            self.latency_data.place_order_total.append(place_latency)
            self.failure_data.place_order_failures += 1
    
    async def cleanup_open_orders(self):
        """Cancel all open Binance orders"""
        if not self.open_orders:
            return
        
        headers = {
            'X-MBX-APIKEY': self.api_key,
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        async with aiohttp.ClientSession() as session:
            for order in self.open_orders[:]:
                try:
                    cancel_params = {
                        'symbol': order['symbol'],
                        'orderId': order['id'],
                        'timestamp': int(time.time() * 1000)
                    }
                    
                    cancel_query = urllib.parse.urlencode(cancel_params)
                    cancel_signature = self._generate_signature(cancel_query)
                    cancel_params['signature'] = cancel_signature
                    
                    async with session.delete(
                        f"{self.base_url_pm}/papi/v1/um/order",
                        headers=headers,
                        data=cancel_params
                    ) as cancel_response:
                        if cancel_response.status == 200:
                            self.open_orders.remove(order)
                            
                except Exception:
                    pass
