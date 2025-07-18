import asyncio
import time
import random
import signal
import statistics
import logging
import os
from typing import List
from rich.live import Live
from rich.table import Table
from rich.console import Console
from .base_exchange import BaseExchange
from .exchange_factory import ExchangeFactory
from .config import DEFAULT_TEST_DURATION, TEST_INTERVAL_MIN, TEST_INTERVAL_MAX, REFRESH_RATE, DECIMAL_PLACES
from .logger import setup_logging, get_logger


class PerformanceTester:
    """Main performance testing class"""
    
    def __init__(self, duration_seconds: int | None = None, force_compatibility_mode: bool = False):
        # Setup logging first
        setup_logging()
        self.logger = get_logger("performance_tester")
        
        self.duration_seconds = duration_seconds if duration_seconds is not None else DEFAULT_TEST_DURATION
        self.exchanges: List[BaseExchange] = []
        self.console = Console()
        self.running = True
        self.force_compatibility_mode = force_compatibility_mode
        
        # Detect terminal environment for compatibility
        self._detect_terminal_environment()
        
        # Capture log file name from the file handler
        self.log_file_name = None
        for handler in logging.getLogger("exchange_performance").handlers:
            if isinstance(handler, logging.FileHandler):
                self.log_file_name = handler.baseFilename
                break
        
        self.logger.info(f"Initializing performance tester with duration: {self.duration_seconds}")
        
        # Initialize exchanges
        self._initialize_exchanges()
        
        # Setup signal handlers for graceful shutdown
        self._setup_signal_handlers()
    
    def _detect_terminal_environment(self):
        """Detect terminal environment and adjust settings for compatibility"""
        self.is_remote_terminal = False
        self.is_ssh = False
        self.effective_refresh_rate = REFRESH_RATE
        
        # Force compatibility mode if requested
        if self.force_compatibility_mode:
            self.is_remote_terminal = True
            self.logger.info("Forced compatibility mode enabled")
        
        # Check for SSH connection
        if 'SSH_CLIENT' in os.environ or 'SSH_TTY' in os.environ or 'SSH_CONNECTION' in os.environ:
            self.is_ssh = True
            self.is_remote_terminal = True
            
        # Check for Windows Terminal over SSH or remote connections
        if (os.environ.get('TERM_PROGRAM') == 'vscode' or 
            'microsoft' in os.environ.get('TERM', '').lower() or
            os.environ.get('WT_SESSION') or
            self.is_ssh):
            self.is_remote_terminal = True
            
        # Adjust refresh rate for remote terminals to reduce flickering
        if self.is_remote_terminal:
            self.effective_refresh_rate = max(0.5, REFRESH_RATE * 0.5)  # Reduce by half, minimum 0.5Hz
            if self.force_compatibility_mode:
                self.effective_refresh_rate = 0.5  # Even slower for forced mode
            self.logger.info(f"Remote terminal detected, reducing refresh rate to {self.effective_refresh_rate}Hz")
        else:
            self.effective_refresh_rate = REFRESH_RATE
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            self.logger.info(f"Received signal {signum}, initiating graceful shutdown")
            self.running = False
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def cleanup_all_orders(self):
        """Cleanup all open orders from all exchanges"""
        cleanup_tasks = []
        total_orders = sum(len(exchange.open_orders) for exchange in self.exchanges)
        
        if total_orders > 0:
            self.logger.info(f"Cleaning up {total_orders} open orders across all exchanges")
        
        for exchange in self.exchanges:
            if exchange.open_orders:
                cleanup_tasks.append(exchange.cleanup_open_orders())
        
        if cleanup_tasks:
            try:
                await asyncio.gather(*cleanup_tasks, return_exceptions=True)
                self.logger.info("Order cleanup completed")
            except Exception as e:
                self.logger.error(f"Error during order cleanup: {e}", exc_info=True)
    
    def _initialize_exchanges(self):
        """Initialize exchange instances using factory"""
        self.exchanges = ExchangeFactory.create_exchanges()
        if self.exchanges:
            exchange_names = [ex.full_name for ex in self.exchanges]
            self.logger.info(f"Initialized {len(self.exchanges)} exchanges: {exchange_names}")
        else:
            self.logger.warning("No exchanges were initialized - check configuration")
    
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
        """Generate expanded hybrid statistics table for display"""
        table = Table(title="Exchange Performance Statistics - Hybrid View")
        table.add_column("Exchange", justify="right", style="cyan", no_wrap=True)
        table.add_column("Action", style="magenta")
        table.add_column("Type", style="white", no_wrap=True)
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
            # Place order stats - Success Only
            place_success_stats = self._calculate_stats(exchange.latency_data.place_order)
            place_failure_rate = exchange.failure_data.get_place_order_failure_rate()
            table.add_row(
                exchange.full_name,
                "Place Order",
                "[green]Success Only[/green]",
                str(place_success_stats['count']),
                self._format_stat_value(place_success_stats['min']),
                self._format_stat_value(place_success_stats['max']),
                self._format_stat_value(place_success_stats['mean']),
                self._format_stat_value(place_success_stats['median']),
                self._format_stat_value(place_success_stats['std_dev']),
                self._format_stat_value(place_success_stats['p95']),
                self._format_stat_value(place_success_stats['p99']),
                self._format_failure_rate(place_failure_rate)
            )
            
            # Place order stats - Total Requests
            place_total_stats = self._calculate_stats(exchange.latency_data.place_order_total)
            table.add_row(
                "",
                "",
                "[blue]All Requests[/blue]",
                str(place_total_stats['count']),
                self._format_stat_value(place_total_stats['min']),
                self._format_stat_value(place_total_stats['max']),
                self._format_stat_value(place_total_stats['mean']),
                self._format_stat_value(place_total_stats['median']),
                self._format_stat_value(place_total_stats['std_dev']),
                self._format_stat_value(place_total_stats['p95']),
                self._format_stat_value(place_total_stats['p99']),
                "-"
            )
            
            # Cancel order stats - Success Only
            cancel_success_stats = self._calculate_stats(exchange.latency_data.cancel_order)
            cancel_failure_rate = exchange.failure_data.get_cancel_order_failure_rate()
            table.add_row(
                "",
                "Cancel Order",
                "[green]Success Only[/green]",
                str(cancel_success_stats['count']),
                self._format_stat_value(cancel_success_stats['min']),
                self._format_stat_value(cancel_success_stats['max']),
                self._format_stat_value(cancel_success_stats['mean']),
                self._format_stat_value(cancel_success_stats['median']),
                self._format_stat_value(cancel_success_stats['std_dev']),
                self._format_stat_value(cancel_success_stats['p95']),
                self._format_stat_value(cancel_success_stats['p99']),
                self._format_failure_rate(cancel_failure_rate)
            )
            
            # Cancel order stats - Total Requests
            cancel_total_stats = self._calculate_stats(exchange.latency_data.cancel_order_total)
            table.add_row(
                "",
                "",
                "[blue]All Requests[/blue]",
                str(cancel_total_stats['count']),
                self._format_stat_value(cancel_total_stats['min']),
                self._format_stat_value(cancel_total_stats['max']),
                self._format_stat_value(cancel_total_stats['mean']),
                self._format_stat_value(cancel_total_stats['median']),
                self._format_stat_value(cancel_total_stats['std_dev']),
                self._format_stat_value(cancel_total_stats['p95']),
                self._format_stat_value(cancel_total_stats['p99']),
                "-"
            )
            
            # Add separator between exchanges
            if exchange != self.exchanges[-1]:  # Not the last exchange
                table.add_row("", "", "", "", "", "", "", "", "", "", "", "")
        
        return table
    
    def _generate_text_summary(self) -> str:
        """Generate a text-based summary of performance statistics for logging"""
        summary_lines = []
        summary_lines.append("=" * 80)
        summary_lines.append("FINAL PERFORMANCE STATISTICS SUMMARY")
        summary_lines.append("=" * 80)
        
        for exchange in self.exchanges:
            summary_lines.append(f"\n{exchange.full_name}:")
            summary_lines.append("-" * 40)
            
            # Place order stats
            place_success_stats = self._calculate_stats(exchange.latency_data.place_order)
            place_total_stats = self._calculate_stats(exchange.latency_data.place_order_total)
            place_failure_rate = exchange.failure_data.get_place_order_failure_rate()
            
            summary_lines.append(f"  Place Order Requests:")
            summary_lines.append(f"    Success Only: {place_success_stats['count']} requests")
            if place_success_stats['count'] > 0:
                summary_lines.append(f"      Mean: {self._format_stat_value(place_success_stats['mean'])}s")
                summary_lines.append(f"      Median: {self._format_stat_value(place_success_stats['median'])}s")
                summary_lines.append(f"      Min: {self._format_stat_value(place_success_stats['min'])}s")
                summary_lines.append(f"      Max: {self._format_stat_value(place_success_stats['max'])}s")
                summary_lines.append(f"      P95: {self._format_stat_value(place_success_stats['p95'])}s")
                summary_lines.append(f"      P99: {self._format_stat_value(place_success_stats['p99'])}s")
            summary_lines.append(f"    Total Requests: {place_total_stats['count']}")
            summary_lines.append(f"    Failure Rate: {place_failure_rate:.1f}%")
            
            # Cancel order stats
            cancel_success_stats = self._calculate_stats(exchange.latency_data.cancel_order)
            cancel_total_stats = self._calculate_stats(exchange.latency_data.cancel_order_total)
            cancel_failure_rate = exchange.failure_data.get_cancel_order_failure_rate()
            
            summary_lines.append(f"  Cancel Order Requests:")
            summary_lines.append(f"    Success Only: {cancel_success_stats['count']} requests")
            if cancel_success_stats['count'] > 0:
                summary_lines.append(f"      Mean: {self._format_stat_value(cancel_success_stats['mean'])}s")
                summary_lines.append(f"      Median: {self._format_stat_value(cancel_success_stats['median'])}s")
                summary_lines.append(f"      Min: {self._format_stat_value(cancel_success_stats['min'])}s")
                summary_lines.append(f"      Max: {self._format_stat_value(cancel_success_stats['max'])}s")
                summary_lines.append(f"      P95: {self._format_stat_value(cancel_success_stats['p95'])}s")
                summary_lines.append(f"      P99: {self._format_stat_value(cancel_success_stats['p99'])}s")
            summary_lines.append(f"    Total Requests: {cancel_total_stats['count']}")
            summary_lines.append(f"    Failure Rate: {cancel_failure_rate:.1f}%")
        
        summary_lines.append("\n" + "=" * 80)
        return "\n".join(summary_lines)
    
    def _log_to_file_only(self, message: str) -> None:
        """Log a message only to the file handler, not to console"""
        # Get the main logger
        main_logger = logging.getLogger("exchange_performance")
        
        # Find the file handler
        file_handler = None
        for handler in main_logger.handlers:
            if isinstance(handler, logging.FileHandler):
                file_handler = handler
                break
        
        # If we have a file handler, log directly to it
        if file_handler:
            record = logging.LogRecord(
                name="exchange_performance.performance_tester",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=message,
                args=(),
                exc_info=None
            )
            # Format the timestamp
            record.created = time.time()
            file_handler.emit(record)

    async def run_test(self):
        """Run the performance test"""
        if not self.exchanges:
            self.console.print("[red]No exchanges configured. Please check your .env file.[/red]")
            return
        
        if self.duration_seconds is None:
            self.console.print("[green]Starting unlimited performance test (press Ctrl+C to stop)...[/green]")
        else:
            self.console.print(f"[green]Starting performance test for {self.duration_seconds} seconds...[/green]")
        
        # Small delay to let the start message be seen
        await asyncio.sleep(1)
        
        start_time = time.time()
        
        # Test functions for each exchange
        test_functions = []
        for exchange in self.exchanges:
            test_functions.extend([
                exchange.test_order_latency,
                exchange.test_order_latency,  # Test order placement more frequently
            ])
        
        self.logger.debug(f"Test functions setup: {[f'{func.__self__.name}.{func.__name__}' for func in test_functions]}")
        
        try:
            # Don't clear screen for remote terminals to avoid flickering
            if not self.is_remote_terminal:
                self.console.clear()
            
            # Print startup info that will remain visible
            self.console.print("[green]Exchange Performance Test - Live Statistics[/green]")
            self.console.print()
            
            # Configure Live display based on terminal environment
            live_config = {
                'console': self.console,
                'refresh_per_second': self.effective_refresh_rate,
                'auto_refresh': True,
                'transient': False
            }
            
            # For remote terminals, use more conservative settings
            if self.is_remote_terminal:
                live_config.update({
                    'transient': True,  # Use transient mode for better remote compatibility
                    'auto_refresh': False  # Manual refresh control for better timing
                })
            
            # Use Rich Live display
            with Live(self.generate_stats_table(), **live_config) as live:
                last_update = time.time()
                update_interval = 1.0 / self.effective_refresh_rate
                
                while self.running:
                    # Check if we should stop based on duration (if not unlimited)
                    if self.duration_seconds is not None and (time.time() - start_time >= self.duration_seconds):
                        break
                        
                    # Randomly select a test function
                    test_func = random.choice(test_functions)
                    
                    try:
                        self.logger.debug(f"Running test function: {test_func.__self__.name}.{test_func.__name__}")
                        await test_func()
                        
                        # Update the live display with controlled timing for remote terminals
                        current_time = time.time()
                        if not self.is_remote_terminal or (current_time - last_update >= update_interval):
                            live.update(self.generate_stats_table())
                            if self.is_remote_terminal:
                                live.refresh()  # Manual refresh for remote terminals
                            last_update = current_time
                            
                    except Exception as e:
                        self.logger.error(f"Test function {test_func.__self__.name}.{test_func.__name__} failed: {e}", exc_info=True)
                    
                    # Wait before next test
                    await asyncio.sleep(random.uniform(TEST_INTERVAL_MIN, TEST_INTERVAL_MAX))

            # Show final table permanently after Live context ends
            final_table = self.generate_stats_table()
            self.console.print(final_table)
            
            # When stopping - show completion message below the final table
            runtime = time.time() - start_time
            
            # Log final statistics summary to file only (not console)
            self._log_to_file_only(f"Performance test completed in {runtime:.2f} seconds")
            self._log_to_file_only(f"Final Performance Statistics Summary:\n{self._generate_text_summary()}")
            
            print()  # Add space after final table
            self.console.print(f"[bold green]🎉 Test completed in {runtime:.2f} seconds![/bold green]")
            if self.log_file_name:
                self.console.print(f"[bold blue]📄 Detailed logs saved to: {self.log_file_name}[/bold blue]")
            print()
        
        finally:
            # Always cleanup orders before exiting
            await self.cleanup_all_orders()
            # Close all exchange connections
            await self.close_all_exchanges()

    async def close_all_exchanges(self):
        """Close all exchange connections"""
        close_tasks = []
        
        for exchange in self.exchanges:
            if hasattr(exchange, 'close') and callable(getattr(exchange, 'close')):
                close_tasks.append(self._safe_close_exchange(exchange))
        
        if close_tasks:
            try:
                await asyncio.gather(*close_tasks, return_exceptions=True)
                self.logger.info("All exchange connections closed")
            except Exception as e:
                self.logger.error(f"Error closing exchanges: {e}", exc_info=True)
    
    async def _safe_close_exchange(self, exchange):
        """Safely close a single exchange with timeout"""
        try:
            # Add timeout to prevent hanging
            await asyncio.wait_for(exchange.close(), timeout=10.0)
            self.logger.info(f"Successfully closed {exchange.full_name}")
        except asyncio.TimeoutError:
            self.logger.error(f"Close timeout for {exchange.full_name}")
            # Force stop WebSocket if it exists
            try:
                if hasattr(exchange, 'ws_client') and exchange.ws_client:
                    exchange.ws_client.stop()
                if hasattr(exchange, 'stream_client') and exchange.stream_client:
                    exchange.stream_client.stop()
            except Exception as e:
                self.logger.error(f"Force close failed for {exchange.full_name}: {e}")
        except Exception as e:
            self.logger.error(f"Error closing {exchange.full_name}: {e}")
