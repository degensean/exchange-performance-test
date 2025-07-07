import asyncio
import time
import random
import signal
import statistics
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
    
    def _format_failure_rate(self, rate: float) -> str:
        """Format failure rate with color coding"""
        if rate <= 2.0:
            return f"[green]{rate:.1f}%[/green]"
        elif rate <= 10.0:
            return f"[yellow]{rate:.1f}%[/yellow]"
        else:
            return f"[red]{rate:.1f}%[/red]"
    
    def _calculate_stats(self, latencies: List[float]) -> dict:
        """Calculate comprehensive statistics for latency data"""
        if not latencies:
            return {
                'count': 0,
                'min': None,
                'max': None,
                'mean': None,
                'median': None,
                'std_dev': None,
                'p50': None,
                'p95': None,
                'p99': None
            }
        
        sorted_latencies = sorted(latencies)
        n = len(latencies)
        
        return {
            'count': n,
            'min': min(latencies),
            'max': max(latencies),
            'mean': statistics.mean(latencies),
            'median': statistics.median(latencies),
            'std_dev': statistics.stdev(latencies) if n > 1 else 0.0,
            'p50': statistics.median(latencies),
            'p95': sorted_latencies[int(0.95 * n)] if n > 0 else None,
            'p99': sorted_latencies[int(0.99 * n)] if n > 0 else None
        }
    
    def _format_stat_value(self, value: float | None) -> str:
        """Format a statistical value for display"""
        if value is None:
            return "-"
        return f"{value:.{DECIMAL_PLACES}f}"

    def generate_stats_table(self) -> Table:
        """Generate statistics table for display"""
        table = Table(title="Exchange Performance Statistics")
        table.add_column("Exchange", justify="right", style="cyan", no_wrap=True)
        table.add_column("Action", style="magenta")
        table.add_column("Count", justify="right", style="green")
        table.add_column("Min (s)", justify="right", style="green")
        table.add_column("Max (s)", justify="right", style="green")
        table.add_column("Mean (s)", justify="right", style="green")
        table.add_column("Median (s)", justify="right", style="blue")
        table.add_column("Std Dev", justify="right", style="yellow")
        table.add_column("P95 (s)", justify="right", style="orange3")
        table.add_column("P99 (s)", justify="right", style="red")
        table.add_column("Failure Rate", justify="right")
        
        for exchange in self.exchanges:
            # Orderbook stats
            orderbook_stats = self._calculate_stats(exchange.latency_data.orderbook)
            failure_rate = exchange.failure_data.get_orderbook_failure_rate()
            table.add_row(
                exchange.name,
                "Orderbook",
                str(orderbook_stats['count']),
                self._format_stat_value(orderbook_stats['min']),
                self._format_stat_value(orderbook_stats['max']),
                self._format_stat_value(orderbook_stats['mean']),
                self._format_stat_value(orderbook_stats['median']),
                self._format_stat_value(orderbook_stats['std_dev']),
                self._format_stat_value(orderbook_stats['p95']),
                self._format_stat_value(orderbook_stats['p99']),
                self._format_failure_rate(failure_rate)
            )
            
            # Place order stats
            place_order_stats = self._calculate_stats(exchange.latency_data.place_order)
            failure_rate = exchange.failure_data.get_place_order_failure_rate()
            table.add_row(
                "",
                "Place Order",
                str(place_order_stats['count']),
                self._format_stat_value(place_order_stats['min']),
                self._format_stat_value(place_order_stats['max']),
                self._format_stat_value(place_order_stats['mean']),
                self._format_stat_value(place_order_stats['median']),
                self._format_stat_value(place_order_stats['std_dev']),
                self._format_stat_value(place_order_stats['p95']),
                self._format_stat_value(place_order_stats['p99']),
                self._format_failure_rate(failure_rate)
            )
            
            # Cancel order stats
            cancel_order_stats = self._calculate_stats(exchange.latency_data.cancel_order)
            failure_rate = exchange.failure_data.get_cancel_order_failure_rate()
            table.add_row(
                "",
                "Cancel Order",
                str(cancel_order_stats['count']),
                self._format_stat_value(cancel_order_stats['min']),
                self._format_stat_value(cancel_order_stats['max']),
                self._format_stat_value(cancel_order_stats['mean']),
                self._format_stat_value(cancel_order_stats['median']),
                self._format_stat_value(cancel_order_stats['std_dev']),
                self._format_stat_value(cancel_order_stats['p95']),
                self._format_stat_value(cancel_order_stats['p99']),
                self._format_failure_rate(failure_rate)
            )
        
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
