import asyncio
import time
import random
import signal
from typing import List
from rich.live import Live
from rich.table import Table
from rich.console import Console
from .base_exchange import BaseExchange
from .exchange_factory import ExchangeFactory
from .config import DEFAULT_TEST_DURATION, TEST_INTERVAL_MIN, TEST_INTERVAL_MAX, REFRESH_RATE, DECIMAL_PLACES


class PerformanceTester:
    """Main performance testing class"""
    
    def __init__(self, duration_seconds: int | None = None):
        self.duration_seconds = duration_seconds or DEFAULT_TEST_DURATION
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
            self.running = False
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def cleanup_all_orders(self):
        """Cleanup all open orders from all exchanges"""
        cleanup_tasks = []
        for exchange in self.exchanges:
            if exchange.open_orders:
                cleanup_tasks.append(exchange.cleanup_open_orders())
        
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
    
    def _initialize_exchanges(self):
        """Initialize exchange instances using factory"""
        self.exchanges = ExchangeFactory.create_exchanges()
    
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
                    f"{min(latencies):.{DECIMAL_PLACES}f}",
                    f"{max(latencies):.{DECIMAL_PLACES}f}",
                    f"{sum(latencies)/len(latencies):.{DECIMAL_PLACES}f}"
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
                    f"{min(latencies):.{DECIMAL_PLACES}f}",
                    f"{max(latencies):.{DECIMAL_PLACES}f}",
                    f"{sum(latencies)/len(latencies):.{DECIMAL_PLACES}f}"
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
                    f"{min(latencies):.{DECIMAL_PLACES}f}",
                    f"{max(latencies):.{DECIMAL_PLACES}f}",
                    f"{sum(latencies)/len(latencies):.{DECIMAL_PLACES}f}"
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
                exchange.test_order_latency,
                exchange.test_order_latency,  # Test order placement more frequently
            ])
        
        try:
            with Live(self.generate_stats_table(), refresh_per_second=REFRESH_RATE, console=self.console) as live:
                while self.running and (time.time() - start_time < self.duration_seconds):
                    # Randomly select a test function
                    test_func = random.choice(test_functions)
                    
                    try:
                        await test_func()
                    except Exception:
                        pass  # Silent error handling for performance testing
                    
                    # Update display
                    live.update(self.generate_stats_table())
                    
                    # Wait before next test
                    await asyncio.sleep(random.uniform(TEST_INTERVAL_MIN, TEST_INTERVAL_MAX))

            self.console.print("[green]Test completed![/green]")
        
        finally:
            # Always cleanup orders before exiting
            await self.cleanup_all_orders()
