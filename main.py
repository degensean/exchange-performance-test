import asyncio
import time
import os
import random
import json
import websockets
import aiohttp
import hmac
import hashlib
import urllib.parse
import signal
import sys
from typing import Dict, List, Optional
from dataclasses import dataclass
from dotenv import load_dotenv
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
import eth_account
from eth_account.signers.local import LocalAccount
from eth_account.account_local_actions import AccountLocalActions
from eth_keys.datatypes import PrivateKey
from rich.live import Live
from rich.table import Table
from rich.console import Console

load_dotenv()

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

class BaseExchange:
    """Base class for exchange implementations"""
    
    def __init__(self, name: str):
        self.name = name
        self.latency_data = LatencyData([], [], [])
        self.latest_orderbook = None  # Store latest orderbook data
        self.latest_price = None      # Store latest mid price from orderbook
        self.open_orders = []         # Track open orders for cleanup
    
    async def test_orderbook_latency(self) -> None:
        """Test orderbook retrieval latency"""
        raise NotImplementedError
    
    async def test_order_latency(self) -> None:
        """Test order placement and cancellation latency"""
        raise NotImplementedError
    
    def get_mid_price_from_orderbook(self) -> Optional[float]:
        """Get mid price from latest orderbook data"""
        if not self.latest_orderbook:
            return None
        
        try:
            # Extract best bid and ask from orderbook
            bids, asks = self._extract_bids_asks(self.latest_orderbook)
            if bids and asks:
                best_bid = float(bids[0][0])  # First bid price
                best_ask = float(asks[0][0])  # First ask price
                return (best_bid + best_ask) / 2
        except Exception as e:
            print(f"Error calculating mid price: {e}")
        return None
    
    def _extract_bids_asks(self, orderbook_data):
        """Extract bids and asks from orderbook data - to be implemented by subclasses"""
        raise NotImplementedError
    
    async def cleanup_open_orders(self):
        """Cancel all open orders - to be implemented by subclasses"""
        raise NotImplementedError

class BinanceExchange(BaseExchange):
    """Binance futures exchange implementation using direct WebSocket API"""
    
    def __init__(self, api_key: str, api_secret: str, symbol: str = "BTCUSDT"):
        super().__init__("Binance")
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbol = symbol
        self.base_url_pm = "https://papi.binance.com"
        self.ws_url = "wss://fstream.binance.com/ws/"
    
    def _generate_signature(self, query_string: str) -> str:
        """Generate HMAC SHA256 signature for Binance API"""
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _get_tick_size(self, price: float) -> float:
        """Get tick size for BTCUSDT on Binance Futures"""
        # For BTCUSDT futures, tick size is typically 0.10 for prices >= 1000
        # and 0.01 for prices < 1000
        if price >= 1000:
            return 0.10
        else:
            return 0.01
    
    def _round_to_tick_size(self, price: float) -> float:
        """Round price to the nearest valid tick size"""
        tick_size = self._get_tick_size(price)
        return round(price / tick_size) * tick_size
    
    def _extract_bids_asks(self, orderbook_data):
        """Extract bids and asks from Binance orderbook data"""
        try:
            # Binance WebSocket format: 'b' for bids, 'a' for asks
            if 'b' in orderbook_data and 'a' in orderbook_data:
                return orderbook_data['b'], orderbook_data['a']
            # Alternative format
            elif 'bids' in orderbook_data and 'asks' in orderbook_data:
                return orderbook_data['bids'], orderbook_data['asks']
            # Nested data format
            elif 'data' in orderbook_data and isinstance(orderbook_data['data'], dict):
                nested_data = orderbook_data['data']
                if 'bids' in nested_data and 'asks' in nested_data:
                    return nested_data['bids'], nested_data['asks']
        except Exception as e:
            print(f"Error extracting bids/asks from Binance data: {e}")
        return None, None
    
    async def test_orderbook_latency(self) -> None:
        """Test Binance futures orderbook latency via websocket"""
        print(f"[DEBUG] {self.name} orderbook test starting...")
        try:
            uri = f"{self.ws_url}{self.symbol.lower()}@depth5@100ms"
            print(f"[DEBUG] Connecting to {uri}")
            
            async with websockets.connect(uri) as websocket:
                start_time = time.time()
                message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                latency = time.time() - start_time
                
                data = json.loads(message)
                print(f"[DEBUG] {self.name} received data keys: {list(data.keys())}")
                
                # Store the latest orderbook data
                self.latest_orderbook = data
                
                # Check for Binance futures WebSocket format: 'b' for bids, 'a' for asks
                if 'b' in data and 'a' in data:
                    self.latency_data.orderbook.append(latency)
                    # Calculate and store latest price
                    self.latest_price = self.get_mid_price_from_orderbook()
                    print(f"[DEBUG] {self.name} orderbook success: {latency:.4f}s, price: {self.latest_price}")
                elif 'bids' in data and 'asks' in data:
                    # Alternative format
                    self.latency_data.orderbook.append(latency)
                    self.latest_price = self.get_mid_price_from_orderbook()
                    print(f"[DEBUG] {self.name} orderbook success (alt format): {latency:.4f}s, price: {self.latest_price}")
                elif 'data' in data and isinstance(data['data'], dict):
                    # Check if data is nested
                    nested_data = data['data']
                    if 'bids' in nested_data and 'asks' in nested_data:
                        self.latency_data.orderbook.append(latency)
                        self.latest_price = self.get_mid_price_from_orderbook()
                        print(f"[DEBUG] {self.name} orderbook success (nested): {latency:.4f}s, price: {self.latest_price}")
                    else:
                        print(f"[DEBUG] {self.name} nested data missing bids/asks: {list(nested_data.keys())}")
                else:
                    print(f"[DEBUG] {self.name} orderbook data structure unknown: {data}")
                    
        except Exception as e:
            print(f"Binance orderbook error: {e}")
    
    async def test_order_latency(self) -> None:
        """Test Binance futures order placement and cancellation latency"""
        print(f"[DEBUG] {self.name} order test starting...")
        
        # Use latest price from orderbook if available
        current_price = self.latest_price
        if not current_price:
            print(f"[DEBUG] {self.name} no current price available from orderbook")
            return
        
        # Place order far below market price to avoid execution
        raw_price = current_price * 0.95  # 5% below market
        price = self._round_to_tick_size(raw_price)  # Round to valid tick size
        print(f"[DEBUG] {self.name} attempting order at price {price} (rounded from {raw_price})")
        
        try:
            # Prepare order parameters
            timestamp = int(time.time() * 1000)
            params = {
                'symbol': self.symbol,
                'side': 'BUY',
                'type': 'LIMIT',
                'timeInForce': 'GTC',
                'quantity': '0.001',
                'price': str(price),
                'timestamp': timestamp
            }
            
            # Create query string and signature
            query_string = urllib.parse.urlencode(params)
            signature = self._generate_signature(query_string)
            params['signature'] = signature
            
            # Place order
            start_time = time.time()
            
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
                    
                    if response.status == 200:
                        order_data = await response.json()
                        self.latency_data.place_order.append(place_latency)
                        
                        # Track the order for cleanup
                        order_id = order_data['orderId']
                        self.open_orders.append({
                            'id': order_id,
                            'symbol': self.symbol,
                            'exchange': 'binance'
                        })
                        
                        # Cancel order
                        cancel_params = {
                            'symbol': self.symbol,
                            'orderId': order_id,
                            'timestamp': int(time.time() * 1000)
                        }
                        
                        cancel_query = urllib.parse.urlencode(cancel_params)
                        cancel_signature = self._generate_signature(cancel_query)
                        cancel_params['signature'] = cancel_signature
                        
                        start_time = time.time()
                        async with session.delete(
                            f"{self.base_url_pm}/papi/v1/um/order",
                            headers=headers,
                            data=cancel_params
                        ) as cancel_response:
                            cancel_latency = time.time() - start_time
                            
                            if cancel_response.status == 200:
                                self.latency_data.cancel_order.append(cancel_latency)
                                # Remove from open orders tracking
                                self.open_orders = [o for o in self.open_orders if o['id'] != order_id]
                    else:
                        error_text = await response.text()
                        print(f"Binance order error: {response.status} - {error_text}")
                        
        except Exception as e:
            print(f"Binance order error: {e}")
    
    async def cleanup_open_orders(self):
        """Cancel all open Binance orders"""
        if not self.open_orders:
            return
        
        print(f"[DEBUG] {self.name} cleaning up {len(self.open_orders)} open orders...")
        
        headers = {
            'X-MBX-APIKEY': self.api_key,
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        async with aiohttp.ClientSession() as session:
            for order in self.open_orders[:]:  # Copy list to avoid modification during iteration
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
                            print(f"[DEBUG] {self.name} cancelled order {order['id']}")
                            self.open_orders.remove(order)
                        else:
                            error_text = await cancel_response.text()
                            print(f"[DEBUG] {self.name} failed to cancel order {order['id']}: {error_text}")
                            
                except Exception as e:
                    print(f"[DEBUG] {self.name} error cancelling order {order['id']}: {e}")

class HyperliquidExchange(BaseExchange):
    """Hyperliquid exchange implementation"""
    
    def __init__(self, wallet_address: str, private_key: str, asset: str = "BTC"):
        super().__init__("Hyperliquid")
        self.wallet_address = wallet_address
        self.private_key = private_key
        self.asset = asset
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        
        # Create LocalAccount for signing
        self.account: LocalAccount = eth_account.Account.from_key(private_key)
        self.exchange = Exchange(self.account, constants.MAINNET_API_URL, account_address=wallet_address)

    def _extract_bids_asks(self, orderbook_data):
        """Extract bids and asks from Hyperliquid orderbook data"""
        try:
            # Check if orderbook_data has 'levels' key with [bids, asks] structure
            if isinstance(orderbook_data, dict) and 'levels' in orderbook_data:
                levels = orderbook_data['levels']
                # levels should be [bids_list, asks_list]
                if isinstance(levels, list) and len(levels) == 2:
                    bids_data, asks_data = levels[0], levels[1]
                    
                    # Convert to standard format [[price, size], ...]
                    bids = []
                    asks = []
                    
                    # Process bids
                    if isinstance(bids_data, list):
                        for bid in bids_data:
                            if isinstance(bid, dict) and 'px' in bid and 'sz' in bid:
                                bids.append([bid['px'], bid['sz']])
                            elif isinstance(bid, list) and len(bid) >= 2:
                                bids.append([bid[0], bid[1]])
                    
                    # Process asks
                    if isinstance(asks_data, list):
                        for ask in asks_data:
                            if isinstance(ask, dict) and 'px' in ask and 'sz' in ask:
                                asks.append([ask['px'], ask['sz']])
                            elif isinstance(ask, list) and len(ask) >= 2:
                                asks.append([ask[0], ask[1]])
                    
                    return bids, asks
                
                # Alternative: levels is a flat list with side indicators
                else:
                    bids = [[level['px'], level['sz']] for level in levels if level.get('side') == 'B']
                    asks = [[level['px'], level['sz']] for level in levels if level.get('side') == 'A']
                    return bids, asks
            
            # Direct list format
            elif isinstance(orderbook_data, list):
                bids = []
                asks = []
                
                for level in orderbook_data:
                    if isinstance(level, dict):
                        # Format: {'px': price, 'sz': size, 'side': 'B'/'A'}
                        if level.get('side') == 'B':
                            bids.append([level['px'], level['sz']])
                        elif level.get('side') == 'A':
                            asks.append([level['px'], level['sz']])
                    elif isinstance(level, list) and len(level) >= 3:
                        # Format: [price, size, side]
                        price, size, side = level[0], level[1], level[2]
                        if side == 'B' or side == 0:
                            bids.append([price, size])
                        elif side == 'A' or side == 1:
                            asks.append([price, size])
                
                return bids, asks
            
            # Standard format with direct bids/asks keys
            elif isinstance(orderbook_data, dict) and 'bids' in orderbook_data and 'asks' in orderbook_data:
                return orderbook_data['bids'], orderbook_data['asks']
            
        except Exception as e:
            print(f"Error extracting bids/asks from Hyperliquid data: {e}")
            print(f"[DEBUG] Hyperliquid data structure: {type(orderbook_data)} - {orderbook_data}")
        return None, None

    def get_current_price(self) -> Optional[float]:
        """Get current BTC price from Hyperliquid"""
        try:
            ticker = self.info.all_mids()
            return float(ticker[self.asset])
        except Exception as e:
            print(f"Error getting Hyperliquid price: {e}")
            return None
    
    async def test_orderbook_latency(self) -> None:
        """Test Hyperliquid orderbook latency"""
        print(f"[DEBUG] {self.name} orderbook test starting...")
        try:
            start_time = time.time()
            # Get L2 book data
            l2_data = self.info.l2_snapshot(self.asset)
            latency = time.time() - start_time
            
            if l2_data:
                # Store the latest orderbook data
                self.latest_orderbook = l2_data
                self.latency_data.orderbook.append(latency)
                # Calculate and store latest price
                self.latest_price = self.get_mid_price_from_orderbook()
                print(f"[DEBUG] {self.name} orderbook success: {latency:.4f}s, price: {self.latest_price}")
            else:
                print(f"[DEBUG] {self.name} orderbook returned no data")
        except Exception as e:
            print(f"Hyperliquid orderbook error: {e}")
    
    async def test_order_latency(self) -> None:
        """Test Hyperliquid order placement and cancellation latency"""
        print(f"[DEBUG] {self.name} order test starting...")
        if not self.exchange:
            print(f"[DEBUG] {self.name} exchange client not initialized")
            return
            
        # Use latest price from orderbook if available
        current_price = self.latest_price
        if not current_price:
            print(f"[DEBUG] {self.name} no current price available from orderbook")
            return
        
        # Place order far below market price to avoid execution
        # Round price to 2 decimal places for BTC (typical for Hyperliquid)
        price = round(current_price * 0.95, 2)  # 5% below market, rounded to 2 decimals
        print(f"[DEBUG] {self.name} attempting order at price {price}")
        
        try:
            # Place order
            start_time = time.time()
            result = self.exchange.order(
                name=self.asset,
                is_buy=True,
                sz=0.01,
                limit_px=price,
                order_type={"limit": {"tif": "Gtc"}},
                reduce_only=False
            )
            
            if result and result.get("status") == "ok":
                place_latency = time.time() - start_time
                self.latency_data.place_order.append(place_latency)
                
                # Try to cancel order
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                if statuses:
                    status = statuses[0]
                    if "resting" in status:
                        order_id = status["resting"]["oid"]
                        
                        # Track the order for cleanup
                        self.open_orders.append({
                            'id': order_id,
                            'asset': self.asset,
                            'exchange': 'hyperliquid'
                        })
                        
                        start_time = time.time()
                        cancel_result = self.exchange.cancel(self.asset, order_id)
                        cancel_latency = time.time() - start_time
                        
                        # Check if cancellation was successful
                        if cancel_result and cancel_result.get("status") == "ok":
                            self.latency_data.cancel_order.append(cancel_latency)
                            # Remove from open orders tracking
                            self.open_orders = [o for o in self.open_orders if o['id'] != order_id]
            else:
                print(f"Hyperliquid order failed: {result}")
            
        except Exception as e:
            print(f"Hyperliquid order error: {e}")
    
    async def cleanup_open_orders(self):
        """Cancel all open Hyperliquid orders"""
        if not self.open_orders:
            return
        
        print(f"[DEBUG] {self.name} cleaning up {len(self.open_orders)} open orders...")
        
        for order in self.open_orders[:]:  # Copy list to avoid modification during iteration
            try:
                result = self.exchange.cancel(order['asset'], order['id'])
                if result and result.get("status") == "ok":
                    print(f"[DEBUG] {self.name} cancelled order {order['id']}")
                    self.open_orders.remove(order)
                else:
                    print(f"[DEBUG] {self.name} failed to cancel order {order['id']}: {result}")
                    
            except Exception as e:
                print(f"[DEBUG] {self.name} error cancelling order {order['id']}: {e}")

class PerformanceTester:
    """Main performance testing class"""
    
    def __init__(self, duration_seconds: int = 60):
        self.duration_seconds = duration_seconds
        self.exchanges: List[BaseExchange] = []
        self.console = Console()
        self.running = True
        
        # Initialize exchanges
        self._initialize_exchanges()
        
        # Setup signal handlers for graceful shutdown
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            print(f"\n[DEBUG] Received signal {signum}, initiating graceful shutdown...")
            self.running = False
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def cleanup_all_orders(self):
        """Cleanup all open orders from all exchanges"""
        print("[DEBUG] Cleaning up all open orders...")
        cleanup_tasks = []
        
        for exchange in self.exchanges:
            if exchange.open_orders:
                cleanup_tasks.append(exchange.cleanup_open_orders())
        
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        print("[DEBUG] Order cleanup completed.")
    
    def _initialize_exchanges(self):
        """Initialize exchange instances"""
        # Binance
        binance_key = os.getenv("BINANCE_API_KEY")
        binance_secret = os.getenv("BINANCE_SECRET_KEY")
        if binance_key and binance_secret:
            self.exchanges.append(BinanceExchange(binance_key, binance_secret))
        
        # Hyperliquid
        hl_address = os.getenv("HYPERLIQUID_API_WALLET_ADDRESS")
        hl_private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY")
        if hl_address and hl_private_key:
            self.exchanges.append(HyperliquidExchange(hl_address, hl_private_key))
    
    def generate_stats_table(self) -> Table:
        """Generate statistics table for display"""
        table = Table(title="Exchange Performance Statistics (in seconds)")
        table.add_column("Exchange", justify="right", style="cyan", no_wrap=True)
        table.add_column("Action", style="magenta")
        table.add_column("Count", justify="right", style="green")
        table.add_column("Min", justify="right", style="green")
        table.add_column("Max", justify="right", style="green")
        table.add_column("Average", justify="right", style="green")
        
        for exchange in self.exchanges:
            # Orderbook stats
            if exchange.latency_data.orderbook:
                latencies = exchange.latency_data.orderbook
                table.add_row(
                    exchange.name,
                    "Orderbook",
                    str(len(latencies)),
                    f"{min(latencies):.4f}",
                    f"{max(latencies):.4f}",
                    f"{sum(latencies)/len(latencies):.4f}"
                )
            else:
                table.add_row(exchange.name, "Orderbook", "0", "-", "-", "-")
            
            # Place order stats
            if exchange.latency_data.place_order:
                latencies = exchange.latency_data.place_order
                table.add_row(
                    "",
                    "Place Order",
                    str(len(latencies)),
                    f"{min(latencies):.4f}",
                    f"{max(latencies):.4f}",
                    f"{sum(latencies)/len(latencies):.4f}"
                )
            else:
                table.add_row("", "Place Order", "0", "-", "-", "-")
            
            # Cancel order stats
            if exchange.latency_data.cancel_order:
                latencies = exchange.latency_data.cancel_order
                table.add_row(
                    "",
                    "Cancel Order",
                    str(len(latencies)),
                    f"{min(latencies):.4f}",
                    f"{max(latencies):.4f}",
                    f"{sum(latencies)/len(latencies):.4f}"
                )
            else:
                table.add_row("", "Cancel Order", "0", "-", "-", "-")
        
        return table
    
    async def run_test(self):
        """Run the performance test"""
        if not self.exchanges:
            self.console.print("[red]No exchanges configured. Please check your .env file.[/red]")
            return
        
        self.console.print(f"[green]Starting performance test for {self.duration_seconds} seconds...[/green]")
        
        start_time = time.time()
        
        # Test functions for each exchange
        test_functions = []
        for exchange in self.exchanges:
            test_functions.extend([
                exchange.test_orderbook_latency,
                exchange.test_order_latency
            ])
        
        try:
            with Live(self.generate_stats_table(), refresh_per_second=2, console=self.console) as live:
                while self.running and (time.time() - start_time < self.duration_seconds):
                    # Randomly select a test function
                    test_func = random.choice(test_functions)
                    
                    try:
                        await test_func()
                    except Exception as e:
                        self.console.print(f"[red]Test error: {e}[/red]")
                    
                    # Update display
                    live.update(self.generate_stats_table())
                    
                    # Wait before next test
                    await asyncio.sleep(random.uniform(0.5, 1.5))

            self.console.print("[green]Test completed![/green]")
        
        finally:
            # Always cleanup orders before exiting
            await self.cleanup_all_orders()

async def main():
    """Main entry point"""
    tester = PerformanceTester(duration_seconds=60)
    await tester.run_test()

if __name__ == "__main__":
    asyncio.run(main())
