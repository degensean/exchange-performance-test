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
    
    async def test_orderbook_latency(self) -> None:
        """Test orderbook retrieval latency"""
        raise NotImplementedError
    
    async def test_order_latency(self) -> None:
        """Test order placement and cancellation latency"""
        raise NotImplementedError
    
    def get_current_price(self) -> Optional[float]:
        """Get current market price"""
        raise NotImplementedError

class BinanceExchange(BaseExchange):
    """Binance futures exchange implementation using direct WebSocket API"""
    
    def __init__(self, api_key: str, api_secret: str, symbol: str = "BTCUSDT"):
        super().__init__("Binance")
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbol = symbol
        self.base_url = "https://fapi.binance.com"
        self.ws_url = "wss://fstream.binance.com/ws/"
    
    def _generate_signature(self, query_string: str) -> str:
        """Generate HMAC SHA256 signature for Binance API"""
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    async def get_current_price(self) -> Optional[float]:
        """Get current BTC price from Binance futures API"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/fapi/v1/ticker/price?symbol={self.symbol}") as response:
                    if response.status == 200:
                        data = await response.json()
                        return float(data['price'])
                    else:
                        print(f"Error getting Binance futures price: {response.status}")
                        return None
        except Exception as e:
            print(f"Error getting Binance futures price: {e}")
            return None
    
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
                
                # Check for Binance futures WebSocket format: 'b' for bids, 'a' for asks
                if 'b' in data and 'a' in data:
                    self.latency_data.orderbook.append(latency)
                    print(f"[DEBUG] {self.name} orderbook success: {latency:.4f}s")
                elif 'bids' in data and 'asks' in data:
                    # Alternative format
                    self.latency_data.orderbook.append(latency)
                    print(f"[DEBUG] {self.name} orderbook success (alt format): {latency:.4f}s")
                elif 'data' in data and isinstance(data['data'], dict):
                    # Check if data is nested
                    nested_data = data['data']
                    if 'bids' in nested_data and 'asks' in nested_data:
                        self.latency_data.orderbook.append(latency)
                        print(f"[DEBUG] {self.name} orderbook success (nested): {latency:.4f}s")
                    else:
                        print(f"[DEBUG] {self.name} nested data missing bids/asks: {list(nested_data.keys())}")
                else:
                    print(f"[DEBUG] {self.name} orderbook data structure unknown: {data}")
                    
        except Exception as e:
            print(f"Binance orderbook error: {e}")
    
    async def test_order_latency(self) -> None:
        """Test Binance futures order placement and cancellation latency"""
        print(f"[DEBUG] {self.name} order test starting...")
        current_price = await self.get_current_price()
        if not current_price:
            print(f"[DEBUG] {self.name} failed to get current price")
            return
        
        # Place order far below market price to avoid execution
        price = round(current_price * 0.95, 2)  # 5% below market
        print(f"[DEBUG] {self.name} attempting order at price {price}")
        
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
                    f"{self.base_url}/fapi/v1/order",
                    headers=headers,
                    data=params
                ) as response:
                    place_latency = time.time() - start_time
                    
                    if response.status == 200:
                        order_data = await response.json()
                        self.latency_data.place_order.append(place_latency)
                        
                        # Cancel order
                        order_id = order_data['orderId']
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
                            f"{self.base_url}/fapi/v1/order",
                            headers=headers,
                            data=cancel_params
                        ) as cancel_response:
                            cancel_latency = time.time() - start_time
                            
                            if cancel_response.status == 200:
                                self.latency_data.cancel_order.append(cancel_latency)
                    else:
                        error_text = await response.text()
                        print(f"Binance order error: {response.status} - {error_text}")
                        
        except Exception as e:
            print(f"Binance order error: {e}")

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
                self.latency_data.orderbook.append(latency)
                print(f"[DEBUG] {self.name} orderbook success: {latency:.4f}s")
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
            
        current_price = self.get_current_price()
        if not current_price:
            print(f"[DEBUG] {self.name} failed to get current price")
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
                        
                        start_time = time.time()
                        self.exchange.cancel(self.asset, order_id)
                        cancel_latency = time.time() - start_time
                        self.latency_data.cancel_order.append(cancel_latency)
            else:
                print(f"Hyperliquid order failed: {result}")
            
        except Exception as e:
            print(f"Hyperliquid order error: {e}")

class PerformanceTester:
    """Main performance testing class"""
    
    def __init__(self, duration_seconds: int = 60):
        self.duration_seconds = duration_seconds
        self.exchanges: List[BaseExchange] = []
        self.console = Console()
        
        # Initialize exchanges
        self._initialize_exchanges()
    
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
        
        with Live(self.generate_stats_table(), refresh_per_second=2, console=self.console) as live:
            while time.time() - start_time < self.duration_seconds:
                # Randomly select a test function
                test_func = random.choice(test_functions)
                
                try:
                    await test_func()
                except Exception as e:
                    self.console.print(f"[red]Test error: {e}[/red]")
                
                # Update display
                live.update(self.generate_stats_table())
                
                # Wait before next test
                await asyncio.sleep(random.uniform(0.5, 2.0))
        
        self.console.print("[green]Test completed![/green]")

async def main():
    """Main entry point"""
    tester = PerformanceTester(duration_seconds=60)
    await tester.run_test()

if __name__ == "__main__":
    asyncio.run(main())

if __name__ == "__main__":
    asyncio.run(main())
