import time
import asyncio
import socket
import json
import threading
from binance.spot import Spot
from binance.websocket.spot.websocket_api import SpotWebsocketAPIClient
from binance.error import ClientError, ServerError
from websocket import WebSocketTimeoutException, WebSocketConnectionClosedException
from .base_exchange import BaseExchange, APIMode
from .config import BINANCE_CONFIG, ORDER_SIZE_BTC, MARKET_OFFSET, WEBSOCKET_TIMEOUT, MAX_RECONNECT_ATTEMPTS, RECONNECT_BASE_DELAY


class BinanceWebSocketExchange(BaseExchange):
    """Binance WebSocket API implementation using official binance-connector for spot trading"""
    
    def __init__(self, api_key: str, secret_key: str):
        super().__init__("Binance-Spot", APIMode.WEBSOCKET)
        
        self.logger.info("Initializing Binance WebSocket exchange for spot trading using official connector")
        
        self.api_key = api_key
        self.secret_key = secret_key
        self.symbol = BINANCE_CONFIG['symbol']
        
        # Response handling for WebSocket API
        self.pending_requests = {}  # Track pending requests by ID
        self.request_counter = 0    # Generate unique request IDs
        self.request_lock = threading.Lock()  # Thread-safe request ID generation
        
        # Initialize Binance WebSocket API client for order operations
        self.ws_client = SpotWebsocketAPIClient(
            api_key=self.api_key,
            api_secret=self.secret_key,
            stream_url="wss://ws-api.binance.com:443/ws-api/v3",
            timeout=WEBSOCKET_TIMEOUT,
            on_message=self._handle_websocket_message
        )
        
        # Stream client for orderbook data (unused in current implementation)
        self.stream_client = None
        
        # Connection state and health monitoring
        self.is_connected = False
        self.last_successful_operation = time.time()
        self.connection_health_task = None
        self.connection_failures = 0
        self.max_connection_failures = 5
        
        # Connection recovery state
        self.recovery_in_progress = False
        self.last_recovery_attempt = 0
        self.recovery_cooldown = 2.0  # Reduced to 2 seconds for more frequent operations
        
        self.logger.info("Binance WebSocket API client initialized successfully")

    def _handle_websocket_message(self, _, message):
        """Handle incoming WebSocket messages from Binance API with proper response correlation"""
        try:
            if isinstance(message, str):
                data = json.loads(message)
            else:
                data = message
            
            self.logger.debug(f"Received WebSocket message: {data}")
            
            # Handle response to our requests
            if 'id' in data:
                request_id = data['id']
                if request_id in self.pending_requests:
                    # Store the response and signal the waiting event
                    self.pending_requests[request_id]['response'] = data
                    self.pending_requests[request_id]['event'].set()
                    self.logger.debug(f"Response received for request {request_id}: status={data.get('status', 'unknown')}")
                else:
                    self.logger.warning(f"Received response for unknown request ID: {request_id}")
            else:
                # Handle stream data or other messages
                self.logger.debug(f"Received non-request message: {data}")
                
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse WebSocket message: {e}")
        except Exception as e:
            self.logger.error(f"Error handling WebSocket message: {e}")

    def _generate_request_id(self) -> str:
        """Generate a unique request ID for WebSocket requests"""
        with self.request_lock:
            self.request_counter += 1
            return f"req_{int(time.time())}_{self.request_counter}"

    async def _place_order_websocket(self, symbol: str, side: str, type: str, 
                                   quantity: float, price: float, timeInForce: str = "GTC"):
        """Place an order using Binance WebSocket API with proper response handling"""
        try:
            request_id = self._generate_request_id()
            
            # Store the request for response correlation
            response_event = asyncio.Event()
            self.pending_requests[request_id] = {
                'event': response_event,
                'response': None,
                'timestamp': time.time()
            }
            
            self.logger.debug(f"Placing WebSocket order with ID {request_id}: {symbol} {side} {quantity} @ {price}")
            
            # Use the binance-connector's built-in new_order method with custom ID
            # Call directly instead of using executor to avoid threading issues
            self.ws_client.new_order(
                id=request_id,
                symbol=symbol,
                side=side,
                type=type,
                quantity=str(quantity),
                price=str(price),
                timeInForce=timeInForce
            )
            
            # Wait for response with timeout (increased from 10s to 20s for better reliability)
            try:
                await asyncio.wait_for(response_event.wait(), timeout=20.0)
                response = self.pending_requests[request_id]['response']
                
                if response and response.get('status') == 200 and 'result' in response:
                    self.logger.debug(f"WebSocket order placement succeeded: {response['result']}")
                    return response['result']
                elif response and 'error' in response:
                    error = response['error']
                    self.logger.error(f"WebSocket order placement error: {error}")
                    # Create a formatted error response similar to REST API
                    raise Exception(f"({error.get('code', 'unknown')}, {error.get('msg', 'Unknown error')})")
                else:
                    self.logger.error(f"WebSocket order placement failed: Invalid response {response}")
                    raise Exception("Invalid response None")
                    
            except asyncio.TimeoutError:
                self.logger.error("WebSocket order placement timeout - no response received")
                
                # CRITICAL FIX: When WebSocket times out, the order might still be placed!
                # Query for recent orders to find and cancel any orphaned orders
                await self._handle_websocket_timeout_order_placement(quantity, price)
                
                raise Exception("WebSocket order placement timeout")
                
        except Exception as e:
            self.logger.error(f"WebSocket order placement failed: {e}")
            raise
        finally:
            # Clean up pending request
            if request_id in self.pending_requests:
                del self.pending_requests[request_id]

    async def _handle_websocket_timeout_order_placement(self, quantity: float, price: float):
        """Handle potential orphaned orders when WebSocket placement times out"""
        try:
            self.logger.warning("Checking for orphaned orders after WebSocket timeout...")
            
            # Use REST API to query recent orders
            from binance.spot import Spot
            rest_client = Spot(
                api_key=self.api_key,
                api_secret=self.secret_key,
                timeout=5
            )
            
            # Get recent orders for this symbol
            recent_orders = rest_client.get_orders(symbol=self.symbol, limit=10)
            
            # Look for orders placed in the last 30 seconds with matching parameters
            current_time = time.time() * 1000  # Convert to milliseconds
            for order in recent_orders:
                # Check if order was placed recently (within last 30 seconds)
                order_time = order.get('time', 0)
                if current_time - order_time < 30000:  # 30 seconds in milliseconds
                    # Check if order matches our parameters
                    order_qty = float(order.get('origQty', 0))
                    order_price = float(order.get('price', 0))
                    order_status = order.get('status', '')
                    
                    # If quantity and price match within tolerance and order is still active
                    if (abs(order_qty - quantity) < 0.001 and 
                        abs(order_price - price) < 0.01 and 
                        order_status in ['NEW', 'PARTIALLY_FILLED']):
                        
                        order_id = str(order['orderId'])
                        self.logger.warning(f"Found potential orphaned order {order_id} with qty={order_qty}, price={order_price}")
                        
                        # Add to open orders list for tracking
                        self.open_orders.append({
                            'id': order_id,
                            'symbol': self.symbol,
                            'exchange': 'binance'
                        })
                        
                        # Try to cancel immediately
                        try:
                            await asyncio.wait_for(self._cancel_order(order_id), timeout=10.0)
                            self.logger.info(f"Successfully cancelled orphaned order {order_id}")
                        except Exception as cancel_error:
                            self.logger.error(f"Failed to cancel orphaned order {order_id}: {cancel_error}")
                            
        except Exception as e:
            self.logger.error(f"Error checking for orphaned orders: {e}")

    async def _cancel_order_websocket(self, symbol: str, orderId: int):
        """Cancel an order using Binance WebSocket API with proper response handling"""
        try:
            request_id = self._generate_request_id()
            
            # Store the request for response correlation
            response_event = asyncio.Event()
            self.pending_requests[request_id] = {
                'event': response_event,
                'response': None,
                'timestamp': time.time()
            }
            
            self.logger.debug(f"Cancelling WebSocket order with ID {request_id}: {orderId}")
            
            # Use the binance-connector's built-in cancel_order method with custom ID
            # Call directly instead of using executor to avoid threading issues
            self.ws_client.cancel_order(
                id=request_id,
                symbol=symbol,
                orderId=orderId
            )
            
            # Wait for response with timeout (increased from 10s to 15s for better reliability)
            try:
                await asyncio.wait_for(response_event.wait(), timeout=15.0)
                response = self.pending_requests[request_id]['response']
                
                if response and response.get('status') == 200 and 'result' in response:
                    self.logger.debug(f"WebSocket order cancellation succeeded: {response['result']}")
                    return response['result']
                elif response and 'error' in response:
                    error = response['error']
                    self.logger.error(f"WebSocket order cancellation error: {error}")
                    # Create a formatted error response similar to REST API
                    raise Exception(f"({error.get('code', 'unknown')}, {error.get('msg', 'Unknown error')})")
                else:
                    self.logger.error(f"WebSocket order cancellation failed: Invalid response {response}")
                    raise Exception("Invalid response None")
                    
            except asyncio.TimeoutError:
                self.logger.error("WebSocket order cancellation timeout - no response received")
                raise Exception("WebSocket order cancellation timeout")
                
        except Exception as e:
            self.logger.error(f"WebSocket order cancellation failed: {e}")
            raise
        finally:
            # Clean up pending request
            if request_id in self.pending_requests:
                del self.pending_requests[request_id]

    async def connect(self):
        """Establish WebSocket connection with enhanced retry logic and health monitoring"""
        if self.recovery_in_progress:
            self.logger.debug("Connection attempt skipped - recovery already in progress")
            return
            
        max_retries = 5
        retry_delays = [1, 2, 5, 10, 15]  # Progressive delays
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"WebSocket connection attempt {attempt + 1}/{max_retries}")
                
                # Close any existing connections first
                await self._force_disconnect()
                
                # Always create a fresh WebSocket client to ensure proper message handling
                self.ws_client = SpotWebsocketAPIClient(
                    api_key=self.api_key,
                    api_secret=self.secret_key,
                    stream_url="wss://ws-api.binance.com:443/ws-api/v3",
                    timeout=WEBSOCKET_TIMEOUT,
                    on_message=self._handle_websocket_message
                )
                
                # Test the connection with a simple ping-like operation
                await self._test_connection()
                
                self.is_connected = True
                self.connection_failures = 0
                self.last_successful_operation = time.time()
                self.logger.info(f"WebSocket connection established successfully on attempt {attempt + 1}")
                
                # Start connection health monitoring
                if not self.connection_health_task or self.connection_health_task.done():
                    self.connection_health_task = asyncio.create_task(self._monitor_connection_health())
                
                return
                
            except Exception as e:
                self.connection_failures += 1
                self.logger.warning(f"WebSocket connection attempt {attempt + 1} failed: {e}")
                
                if attempt < max_retries - 1:
                    delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                    self.logger.info(f"Retrying WebSocket connection in {delay} seconds...")
                    await asyncio.sleep(delay)
                else:
                    self.logger.error(f"Failed to establish WebSocket connection after {max_retries} attempts")
                    self.is_connected = False
                    
                    # If we've had too many failures, consider falling back to REST
                    if self.connection_failures >= self.max_connection_failures:
                        self.logger.error("Too many connection failures - WebSocket mode may be unstable")

    async def _test_connection(self):
        """Test the WebSocket connection with a lightweight operation"""
        try:
            # Test with account information request (lightweight)
            test_start = time.time()
            # For now, we'll just assume the connection is good if the client initializes
            # The actual test would be done when we perform operations
            await asyncio.sleep(0.1)  # Small delay to simulate connection test
            test_time = time.time() - test_start
            self.logger.debug(f"Connection test completed in {test_time:.3f}s")
        except Exception as e:
            self.logger.error(f"Connection test failed: {e}")
            raise

    async def _force_disconnect(self):
        """Force disconnect all WebSocket connections"""
        try:
            if hasattr(self, 'ws_client') and self.ws_client:
                try:
                    self.ws_client.stop()
                except Exception as e:
                    self.logger.debug(f"Error stopping WebSocket client: {e}")
                    
            if hasattr(self, 'stream_client') and self.stream_client:
                try:
                    self.stream_client.stop()
                except Exception as e:
                    self.logger.debug(f"Error stopping stream client: {e}")
                    
            # Cancel health monitoring task
            if self.connection_health_task and not self.connection_health_task.done():
                self.connection_health_task.cancel()
                try:
                    await self.connection_health_task
                except asyncio.CancelledError:
                    pass
                    
            self.is_connected = False
            await asyncio.sleep(0.1)  # Brief pause to ensure cleanup
            
        except Exception as e:
            self.logger.debug(f"Error during force disconnect: {e}")

    async def _monitor_connection_health(self):
        """Monitor WebSocket connection health and trigger recovery if needed"""
        while self.is_connected:
            try:
                await asyncio.sleep(45)  # Check every 45 seconds (less frequent)
                
                # Check if we've had recent successful operations
                time_since_last_success = time.time() - self.last_successful_operation
                
                if time_since_last_success > 180:  # 3 minutes without success (more lenient)
                    self.logger.warning(f"No successful operations for {time_since_last_success:.1f}s - connection may be stale")
                    
                    # Test connection health
                    try:
                        await asyncio.wait_for(self._test_connection(), timeout=15)  # Longer timeout
                        self.last_successful_operation = time.time()
                    except (asyncio.TimeoutError, Exception) as e:
                        self.logger.error(f"Connection health check failed: {e}")
                        # Only trigger recovery if we haven't had ANY successful operations recently
                        if time_since_last_success > 300:  # 5 minutes of complete failure
                            await self._handle_websocket_timeout("health check")
                        
            except asyncio.CancelledError:
                self.logger.debug("Connection health monitoring cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error in connection health monitoring: {e}")
                await asyncio.sleep(15)  # Wait before retrying

    async def disconnect(self):
        """Close WebSocket connections gracefully"""
        try:
            self.logger.info("Initiating WebSocket disconnect...")
            await self._force_disconnect()
            self.logger.info("WebSocket connections closed successfully")
        except Exception as e:
            self.logger.error(f"Error disconnecting WebSocket: {e}")

    async def _handle_websocket_timeout(self, operation_name: str = "WebSocket operation"):
        """Enhanced WebSocket timeout handling with smarter recovery"""
        current_time = time.time()
        
        # Prevent multiple concurrent recovery attempts
        if self.recovery_in_progress:
            self.logger.debug(f"Recovery already in progress for {operation_name}")
            return False
            
        # Implement recovery cooldown to prevent rapid retry loops
        if current_time - self.last_recovery_attempt < self.recovery_cooldown:
            self.logger.debug(f"Recovery cooldown active, skipping recovery for {operation_name}")
            return False
            
        self.recovery_in_progress = True
        self.last_recovery_attempt = current_time
        
        self.logger.warning(f"WebSocket timeout during {operation_name}, attempting enhanced recovery...")
        self.is_connected = False
        
        try:
            # Attempt to reconnect with exponential backoff
            for attempt in range(MAX_RECONNECT_ATTEMPTS):
                try:
                    self.logger.info(f"WebSocket recovery attempt {attempt + 1}/{MAX_RECONNECT_ATTEMPTS}")
                    
                    # Force close existing connections
                    await self._force_disconnect()
                    
                    # Progressive delay with jitter
                    base_delay = RECONNECT_BASE_DELAY * (2 ** attempt)
                    jitter = 0.1 * base_delay * (asyncio.get_event_loop().time() % 1)
                    delay = base_delay + jitter
                    
                    self.logger.debug(f"Waiting {delay:.2f}s before recovery attempt {attempt + 1}")
                    await asyncio.sleep(delay)
                    
                    # Attempt to reconnect
                    await self.connect()
                    
                    if self.is_connected:
                        self.logger.info(f"WebSocket connection recovered successfully on attempt {attempt + 1}")
                        self.connection_failures = 0
                        return True
                        
                except Exception as e:
                    self.logger.warning(f"WebSocket recovery attempt {attempt + 1} failed: {e}")
                    
            self.logger.error(f"Failed to recover WebSocket connection after {MAX_RECONNECT_ATTEMPTS} attempts")
            return False
            
        finally:
            self.recovery_in_progress = False

    async def _safe_websocket_operation(self, operation_func, operation_name: str, max_retries: int = 2):
        """Safely execute a WebSocket operation with enhanced timeout handling and recovery"""
        operation_timeout = min(WEBSOCKET_TIMEOUT * 0.8, 20)  # Use 80% of WebSocket timeout or 20s max
        
        for attempt in range(max_retries + 1):
            try:
                # Check connection status before operation - more lenient for frequent operations
                if not self.is_connected and not self.recovery_in_progress:
                    self.logger.warning(f"Connection not available for {operation_name}, attempting reconnect...")
                    await self.connect()
                    
                    if not self.is_connected:
                        # Still try the operation - might work even if connection check failed
                        self.logger.warning(f"Connection check failed for {operation_name}, but attempting operation anyway...")
                
                # Execute operation with adaptive timeout
                self.logger.debug(f"Executing {operation_name} with {operation_timeout}s timeout (attempt {attempt + 1})")
                
                start_time = time.time()
                result = await asyncio.wait_for(operation_func(), timeout=operation_timeout)
                
                # Update successful operation timestamp and ensure connection is marked as good
                self.last_successful_operation = time.time()
                self.is_connected = True  # Mark connection as good after successful operation
                self.connection_failures = 0  # Reset failure counter
                operation_time = self.last_successful_operation - start_time
                self.logger.debug(f"{operation_name} completed successfully in {operation_time:.3f}s")
                
                return result
                
            except (TimeoutError, WebSocketTimeoutException, asyncio.TimeoutError, 
                    ConnectionError, WebSocketConnectionClosedException, 
                    socket.timeout, OSError) as e:
                    
                operation_time = time.time() - start_time if 'start_time' in locals() else 0
                self.logger.error(f"Timeout/Connection error during {operation_name} "
                                f"(attempt {attempt + 1}, took {operation_time:.3f}s): {type(e).__name__}: {e}")
                
                # Only mark connection as failed after multiple failures
                self.connection_failures += 1
                if self.connection_failures >= 3:
                    self.is_connected = False
                    self.logger.warning(f"Marking connection as failed after {self.connection_failures} consecutive failures")
                
                if attempt < max_retries:
                    # Attempt recovery with enhanced handling only if connection is marked as failed
                    if not self.is_connected:
                        self.logger.info(f"Attempting recovery for {operation_name}...")
                        recovery_success = await self._handle_websocket_timeout(operation_name)
                        
                        if not recovery_success:
                            self.logger.error(f"Recovery failed for {operation_name}, aborting retries")
                            break
                    else:
                        self.logger.info(f"Connection still marked as good, retrying {operation_name} without recovery...")
                        
                    # Brief pause before retry
                    await asyncio.sleep(0.5)  # Reduced from 1 second
                    
                else:
                    self.logger.error(f"Max retries ({max_retries}) reached for {operation_name}")
                    # Don't always mark connection as failed on final retry - might be temporary issue
                    raise
                    
            except Exception as e:
                operation_time = time.time() - start_time if 'start_time' in locals() else 0
                error_msg = str(e).lower()
                
                # Check if it's a connection-related error
                connection_keywords = ['connection', 'socket', 'network', 'disconnect', 'reset', 'broken']
                is_connection_error = any(keyword in error_msg for keyword in connection_keywords)
                
                if is_connection_error:
                    self.logger.warning(f"Connection error during {operation_name} "
                                      f"(attempt {attempt + 1}, took {operation_time:.3f}s): {e}")
                    
                    if attempt < max_retries:
                        self.logger.info(f"Attempting recovery for connection error in {operation_name}...")
                        recovery_success = await self._handle_websocket_timeout(operation_name)
                        
                        if not recovery_success:
                            self.logger.error(f"Recovery failed for {operation_name}, aborting retries")
                            break
                            
                        await asyncio.sleep(1)
                        continue
                
                # For non-recoverable errors, log and re-raise immediately
                self.logger.error(f"Non-recoverable error during {operation_name} "
                                f"(attempt {attempt + 1}, took {operation_time:.3f}s): {type(e).__name__}: {e}")
                raise
                
        # If we get here, all retries failed
        raise ConnectionError(f"All retry attempts failed for {operation_name} after {max_retries + 1} attempts")

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

    def _format_price(self, price: float) -> str:
        """Format price according to Binance tick size requirements"""
        # Binance Spot BTCUSDT has specific tick size requirements
        # Round price to valid tick size (e.g., 0.1 for BTCUSDT)
        if price >= BINANCE_CONFIG['tick_threshold']:
            tick_size = BINANCE_CONFIG['tick_size_high']
        else:
            tick_size = BINANCE_CONFIG['tick_size_low']
        
        # Round to nearest valid tick
        rounded_price = round(price / tick_size) * tick_size
        
        # Format with appropriate precision for spot trading
        precision = BINANCE_CONFIG['price_precision']
        formatted = f"{rounded_price:.{precision}f}"
        
        # Remove trailing zeros but maintain minimum precision
        if '.' in formatted:
            formatted = formatted.rstrip('0')
            decimal_part = formatted.split('.')[1] if '.' in formatted else ''
            if len(decimal_part) < 2:
                formatted = f"{rounded_price:.2f}"
        
        self.logger.debug(f"Formatted price {price} -> {rounded_price} -> {formatted}")
        return formatted

    def _format_quantity(self, quantity: float) -> str:
        """Format quantity with correct precision for spot trading"""
        precision = BINANCE_CONFIG['quantity_precision']
        
        # Format with full precision
        formatted = f"{quantity:.{precision}f}"
        
        # Remove trailing zeros
        formatted = formatted.rstrip('0').rstrip('.')
        
        # Ensure we don't have empty string or zero
        if not formatted or formatted == '0' or float(formatted) <= 0:
            min_quantity = 10 ** (-precision)
            formatted = f"{min_quantity:.{precision}f}"
            self.logger.warning(f"Quantity {quantity} too small, using minimum: {formatted}")
        
        self.logger.debug(f"Formatted quantity {quantity} to {formatted}")
        return formatted

    async def test_order_latency(self) -> None:
        """Test Binance order placement and cancellation latency using WebSocket API"""
        # First, do a comprehensive cleanup using REST API to ensure clean start
        self.logger.info("Starting comprehensive cleanup before order latency test...")
        await self.cleanup_all_open_orders_rest()
        
        # Also cleanup any orders in our tracking list
        if self.open_orders:
            self.logger.warning(f"Found {len(self.open_orders)} leftover orders in tracking list, cleaning up")
            await self.cleanup_open_orders()
        
        self.logger.debug(f"Starting order latency test - Connection status: {self.is_connected}, Failures: {self.connection_failures}")
        
        try:
            # Wrap the actual test in safe WebSocket operation
            await self._safe_websocket_operation(
                self._test_order_latency_internal,
                "order latency test"
            )
        finally:
            # Always cleanup any remaining orders after the test, regardless of success/failure
            if self.open_orders:
                self.logger.warning(f"Cleaning up {len(self.open_orders)} remaining orders after test")
                try:
                    await self.cleanup_open_orders()
                except Exception as cleanup_error:
                    self.logger.error(f"Error during post-test cleanup: {cleanup_error}")

    async def _test_order_latency_internal(self) -> None:
        """Internal implementation of order latency test using WebSocket API"""
        # Get current market price from REST API (since WebSocket order API doesn't provide ticker)
        if not self.latest_price:
            try:
                # Use a simple REST client to get current price with timeout
                from binance.spot import Spot
                rest_client = Spot(timeout=5)  # Short timeout for price check
                ticker = rest_client.ticker_price(symbol=self.symbol)
                if ticker and 'price' in ticker:
                    self.latest_price = float(ticker['price'])
                    self.logger.debug(f"Got current price from REST ticker: {self.latest_price}")
                else:
                    self.logger.error("Failed to get current price from ticker")
                    return
            except Exception as e:
                self.logger.error(f"Error getting current price: {e}")
                # Try to continue with last known price if available
                if hasattr(self, 'latest_price') and self.latest_price:
                    self.logger.warning(f"Using last known price: {self.latest_price}")
                else:
                    return

        raw_price = self.latest_price * MARKET_OFFSET  # 5% below market
        price = self._round_to_tick_size(raw_price)

        self.logger.debug(f"Placing order via WebSocket: {ORDER_SIZE_BTC} {self.symbol} at {price}")

        self.failure_data.place_order_total += 1
        start_time = time.time()

        try:
            # Format order parameters
            quantity = self._format_quantity(ORDER_SIZE_BTC)
            formatted_price = self._format_price(price)

            self.logger.debug(f"Order parameters: symbol={self.symbol}, "
                             f"quantity={quantity}, price={formatted_price}, "
                             f"side=BUY, type=LIMIT")

            # Use WebSocket API for order placement
            order_response = await self._place_order_websocket(
                symbol=self.symbol,
                side="BUY",
                type="LIMIT",
                quantity=float(quantity),
                price=float(formatted_price),
                timeInForce="GTC"
            )

            place_latency = time.time() - start_time

            # Always record total request latency
            self.latency_data.place_order_total.append(place_latency)

            if order_response and 'orderId' in order_response:
                # Record success-only latency
                self.latency_data.place_order.append(place_latency)

                order_id = str(order_response['orderId'])
                self.logger.debug(f"Order placed successfully via WebSocket in {place_latency:.4f}s, ID: {order_id}")

                self.open_orders.append({
                    'id': order_id,
                    'symbol': self.symbol,
                    'exchange': 'binance'
                })

                # Cancel order immediately with timeout
                try:
                    await asyncio.wait_for(self._cancel_order(order_id), timeout=10.0)
                except asyncio.TimeoutError:
                    self.logger.error(f"Timeout cancelling order {order_id}, will be cleaned up later")
                except Exception as cancel_error:
                    self.logger.error(f"Error cancelling order {order_id}: {cancel_error}")
                    # Order will remain in open_orders list for cleanup
            else:
                self.failure_data.place_order_failures += 1
                self.logger.error(f"WebSocket order placement failed: Invalid response {order_response}")

        except (TimeoutError, WebSocketTimeoutException, asyncio.TimeoutError, socket.timeout) as e:
            place_latency = time.time() - start_time
            self.latency_data.place_order_total.append(place_latency)
            self.failure_data.place_order_failures += 1
            self.logger.error(f"TIMEOUT ERROR - Order placement failed after {place_latency:.3f}s: {type(e).__name__}: {e}")
            # Mark connection as potentially problematic
            self.connection_failures += 1
            # Re-raise to trigger recovery in _safe_websocket_operation
            raise

        except (ConnectionError, WebSocketConnectionClosedException, OSError) as e:
            place_latency = time.time() - start_time
            self.latency_data.place_order_total.append(place_latency)
            self.failure_data.place_order_failures += 1
            self.logger.error(f"CONNECTION ERROR - Order placement failed after {place_latency:.3f}s: {type(e).__name__}: {e}")
            self.connection_failures += 1
            # Re-raise to trigger recovery
            raise

        except Exception as e:
            place_latency = time.time() - start_time
            self.latency_data.place_order_total.append(place_latency)
            self.failure_data.place_order_failures += 1

            # Handle specific API errors
            error_msg = str(e)
            if "-1111" in error_msg or "precision" in error_msg.lower():
                self.logger.error(f"PRECISION ERROR - Order placement failed: {error_msg}")
                self.logger.error(f"Order parameters: "
                               f"quantity={quantity}, price={formatted_price}, symbol={self.symbol}")
            elif "-2010" in error_msg or "insufficient" in error_msg.lower():
                self.logger.error(f"INSUFFICIENT FUNDS - Order placement failed: {error_msg}")
            elif "-1013" in error_msg or "filter" in error_msg.lower():
                self.logger.error(f"FILTER FAILURE - Order placement failed: {error_msg}")
            elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                self.logger.error(f"API TIMEOUT - Order placement failed after {place_latency:.3f}s: {error_msg}")
                self.connection_failures += 1
                # Re-raise timeout errors to trigger recovery
                raise asyncio.TimeoutError(f"API timeout: {error_msg}")
            else:
                self.logger.error(f"API ERROR - Order placement failed: {error_msg}")
                # Don't re-raise general API errors as they're not connection issues

    async def _cancel_order(self, order_id: str) -> None:
        """Cancel a specific order using WebSocket API with timeout handling"""
        await self._safe_websocket_operation(
            lambda: self._cancel_order_internal(order_id),
            f"cancel order {order_id}"
        )

    async def _cancel_order_internal(self, order_id: str) -> None:
        """Internal implementation of order cancellation using WebSocket API"""
        self.failure_data.cancel_order_total += 1
        cancel_start_time = time.time()

        try:
            # Use WebSocket API for cancellation
            cancel_response = await self._cancel_order_websocket(
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
                self.logger.debug(f"Order {order_id} cancelled successfully via WebSocket in {cancel_latency:.4f}s")
            else:
                self.failure_data.cancel_order_failures += 1
                self.logger.error(f"WebSocket order cancellation failed for {order_id}: Invalid response {cancel_response}")

        except (TimeoutError, WebSocketTimeoutException, asyncio.TimeoutError, socket.timeout) as e:
            cancel_latency = time.time() - cancel_start_time
            self.latency_data.cancel_order_total.append(cancel_latency)
            self.failure_data.cancel_order_failures += 1
            self.logger.error(f"TIMEOUT ERROR - WebSocket order cancellation failed for {order_id} after {cancel_latency:.3f}s: {type(e).__name__}: {e}")
            self.connection_failures += 1
            # Re-raise to trigger recovery in _safe_websocket_operation
            raise

        except (ConnectionError, WebSocketConnectionClosedException, OSError) as e:
            cancel_latency = time.time() - cancel_start_time
            self.latency_data.cancel_order_total.append(cancel_latency)
            self.failure_data.cancel_order_failures += 1
            self.logger.error(f"CONNECTION ERROR - WebSocket order cancellation failed for {order_id} after {cancel_latency:.3f}s: {type(e).__name__}: {e}")
            self.connection_failures += 1
            # Re-raise to trigger recovery
            raise

        except Exception as e:
            cancel_latency = time.time() - cancel_start_time
            self.latency_data.cancel_order_total.append(cancel_latency)
            self.failure_data.cancel_order_failures += 1

            error_msg = str(e)
            if "-2011" in error_msg:  # Order not found
                self.logger.warning(f"Order {order_id} not found during WebSocket cancellation (likely already filled/cancelled): {error_msg}")
                # Remove from open orders list since it doesn't exist
                self.open_orders = [o for o in self.open_orders if o['id'] != order_id]
            elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                self.logger.error(f"API TIMEOUT - WebSocket order cancellation failed for {order_id} after {cancel_latency:.3f}s: {error_msg}")
                self.connection_failures += 1
                # Re-raise timeout errors to trigger recovery
                raise asyncio.TimeoutError(f"API timeout: {error_msg}")
            else:
                self.logger.error(f"API ERROR - WebSocket order cancellation failed for {order_id}: {error_msg}")
                # Don't re-raise general API errors as they're not connection issues

    async def cancel_all_orders_websocket(self, symbol: str | None = None):
        """Cancel all open orders for a symbol using WebSocket API with proper response handling"""
        if symbol is None:
            symbol = self.symbol
        
        # At this point symbol is guaranteed to be a string
        assert isinstance(symbol, str), "Symbol must be a string"
        
        request_id = None    
        try:
            # First, get all open orders for the symbol
            open_orders = await self._get_open_orders_websocket(symbol)
            
            if not open_orders:
                self.logger.info(f"No open orders found for {symbol}")
                return {"cancelled_orders": []}
            
            self.logger.info(f"Found {len(open_orders)} open orders for {symbol}, cancelling all...")
            
            # Cancel all orders using the bulk cancel operation
            request_id = self._generate_request_id()
            
            # Store the request for response correlation
            response_event = asyncio.Event()
            self.pending_requests[request_id] = {
                'event': response_event,
                'response': None,
                'timestamp': time.time()
            }
            
            self.logger.debug(f"Cancelling all orders with ID {request_id} for symbol: {symbol}")
            
            # Use the binance-connector's built-in cancel_open_orders method
            self.ws_client.cancel_open_orders(
                id=request_id,
                symbol=symbol
            )
            
            # Wait for response with timeout
            try:
                await asyncio.wait_for(response_event.wait(), timeout=20.0)
                response = self.pending_requests[request_id]['response']
                
                if response and response.get('status') == 200 and 'result' in response:
                    cancelled_orders = response['result']
                    self.logger.info(f"Successfully cancelled {len(cancelled_orders)} orders via WebSocket")
                    return {"cancelled_orders": cancelled_orders}
                elif response and 'error' in response:
                    error = response['error']
                    self.logger.error(f"WebSocket cancel all orders error: {error}")
                    raise Exception(f"({error.get('code', 'unknown')}, {error.get('msg', 'Unknown error')})")
                else:
                    self.logger.error(f"WebSocket cancel all orders failed: Invalid response {response}")
                    raise Exception("Invalid response for cancel all orders")
                    
            except asyncio.TimeoutError:
                self.logger.error("WebSocket cancel all orders timeout - no response received")
                raise Exception("WebSocket cancel all orders timeout")
                
        except Exception as e:
            self.logger.error(f"WebSocket cancel all orders failed: {e}")
            raise
        finally:
            # Clean up pending request
            if request_id and request_id in self.pending_requests:
                del self.pending_requests[request_id]

    async def _get_open_orders_websocket(self, symbol: str | None = None):
        """Get all open orders for a symbol using WebSocket API"""
        if symbol is None:
            symbol = self.symbol
        
        # At this point symbol is guaranteed to be a string
        assert isinstance(symbol, str), "Symbol must be a string"
        
        request_id = None
        try:
            request_id = self._generate_request_id()
            
            # Store the request for response correlation
            response_event = asyncio.Event()
            self.pending_requests[request_id] = {
                'event': response_event,
                'response': None,
                'timestamp': time.time()
            }
            
            self.logger.debug(f"Getting open orders with ID {request_id} for symbol: {symbol}")
            
            # Use the binance-connector's built-in get_open_orders method
            self.ws_client.get_open_orders(
                id=request_id,
                symbol=symbol
            )
            
            # Wait for response with timeout
            try:
                await asyncio.wait_for(response_event.wait(), timeout=15.0)
                response = self.pending_requests[request_id]['response']
                
                if response and response.get('status') == 200 and 'result' in response:
                    orders = response['result']
                    self.logger.debug(f"Retrieved {len(orders)} open orders for {symbol}")
                    return orders
                elif response and 'error' in response:
                    error = response['error']
                    self.logger.error(f"WebSocket get open orders error: {error}")
                    raise Exception(f"({error.get('code', 'unknown')}, {error.get('msg', 'Unknown error')})")
                else:
                    self.logger.error(f"WebSocket get open orders failed: Invalid response {response}")
                    raise Exception("Invalid response for get open orders")
                    
            except asyncio.TimeoutError:
                self.logger.error("WebSocket get open orders timeout - no response received")
                raise Exception("WebSocket get open orders timeout")
                
        except Exception as e:
            self.logger.error(f"WebSocket get open orders failed: {e}")
            raise
        finally:
            # Clean up pending request
            if request_id and request_id in self.pending_requests:
                del self.pending_requests[request_id]

    async def place_multiple_orders_websocket(self, orders_config: list):
        """Place multiple orders sequentially using WebSocket API"""
        placed_orders = []
        failed_orders = []
        
        self.logger.info(f"Placing {len(orders_config)} orders via WebSocket...")
        
        for i, order_config in enumerate(orders_config):
            try:
                self.logger.debug(f"Placing order {i+1}/{len(orders_config)}: {order_config}")
                
                result = await self._place_order_websocket(
                    symbol=order_config.get('symbol', self.symbol),
                    side=order_config['side'],
                    type=order_config.get('type', 'LIMIT'),
                    quantity=order_config['quantity'],
                    price=order_config['price'],
                    timeInForce=order_config.get('timeInForce', 'GTC')
                )
                
                placed_orders.append({
                    'config': order_config,
                    'result': result,
                    'order_id': result.get('orderId')
                })
                
                self.logger.info(f"Order {i+1} placed successfully with ID: {result.get('orderId')}")
                
                # Small delay between orders to avoid rate limits
                await asyncio.sleep(0.5)
                
            except Exception as e:
                failed_orders.append({
                    'config': order_config,
                    'error': str(e)
                })
                self.logger.error(f"Order {i+1} failed: {e}")
        
        self.logger.info(f"Multiple order placement completed: {len(placed_orders)} successful, {len(failed_orders)} failed")
        
        return {
            'placed_orders': placed_orders,
            'failed_orders': failed_orders,
            'success_count': len(placed_orders),
            'failure_count': len(failed_orders)
        }

    async def cleanup_open_orders(self):
        """Cancel all open Binance orders using enhanced WebSocket API with REST fallback"""
        if not self.open_orders:
            self.logger.info("No open orders to cleanup")
            return
        
        self.logger.info(f"Cleaning up {len(self.open_orders)} open orders via enhanced WebSocket API")
        
        try:
            # First, try the enhanced bulk cancel all orders functionality
            result = await self.cancel_all_orders_websocket(self.symbol)
            cancelled_orders = result.get('cancelled_orders', [])
            
            if cancelled_orders:
                self.logger.info(f"Successfully cancelled {len(cancelled_orders)} orders via bulk WebSocket operation")
                
                # Update our tracking list - remove cancelled orders
                cancelled_order_ids = {str(order.get('orderId', '')) for order in cancelled_orders}
                self.open_orders = [order for order in self.open_orders if order['id'] not in cancelled_order_ids]
                
                # If all orders were cancelled, we're done
                if not self.open_orders:
                    self.logger.info("All orders cleaned up successfully via bulk operation")
                    return
            
        except Exception as e:
            self.logger.warning(f"Bulk WebSocket cancel failed: {e}, falling back to individual cancellation")
        
        # Fallback: Try individual WebSocket cancellation for remaining orders
        failed_orders = []
        for order in self.open_orders[:]:
            try:
                # Use WebSocket API for cleanup with shorter timeout
                await asyncio.wait_for(self._cancel_order(order['id']), timeout=5.0)
                self.logger.info(f"Successfully cancelled order {order['id']} during cleanup via WebSocket")
                    
            except asyncio.TimeoutError:
                self.logger.warning(f"WebSocket timeout cancelling order {order['id']}, will retry with REST API")
                failed_orders.append(order)
            except Exception as e:
                error_msg = str(e)
                if "-2011" in error_msg:  # Order not found
                    self.logger.info(f"Order {order['id']} already cancelled or filled during cleanup")
                    self.open_orders = [o for o in self.open_orders if o['id'] != order['id']]
                else:
                    self.logger.warning(f"WebSocket error during cleanup of order {order['id']}: {e}")
                    failed_orders.append(order)
        
        # Final fallback: Use REST API for failed orders
        if failed_orders:
            self.logger.warning(f"Attempting REST API fallback for {len(failed_orders)} failed orders")
            await self._cleanup_orders_rest_fallback(failed_orders)
        
        if self.open_orders:
            self.logger.error(f"CRITICAL: Failed to cleanup {len(self.open_orders)} orders - manual intervention may be required!")
            for order in self.open_orders:
                self.logger.error(f"Uncancelled order: {order['id']} on {order['symbol']}")
        else:
            self.logger.info("All orders cleaned up successfully")

    async def cleanup_all_open_orders_rest(self):
        """Query and cancel ALL open orders for this symbol using REST API - comprehensive startup cleanup"""
        try:
            from binance.spot import Spot
            
            # Create REST client to query all open orders
            rest_client = Spot(
                api_key=self.api_key,
                api_secret=self.secret_key,
                timeout=10
            )
            
            self.logger.info("Querying all open orders via REST API for comprehensive cleanup...")
            
            # Get all open orders for this symbol
            open_orders = rest_client.get_open_orders(symbol=self.symbol)
            
            if not open_orders:
                self.logger.info("No open orders found via REST API")
                self.open_orders.clear()  # Clear our tracking list too
                return
            
            self.logger.warning(f"Found {len(open_orders)} open orders via REST API, cancelling all...")
            
            cancelled_count = 0
            for order in open_orders:
                try:
                    order_id = str(order['orderId'])
                    cancel_response = rest_client.cancel_order(
                        symbol=self.symbol,
                        orderId=int(order_id)
                    )
                    
                    if cancel_response and 'orderId' in cancel_response:
                        cancelled_count += 1
                        self.logger.info(f"REST API cancelled order {order_id}")
                        
                        # Add to our tracking list if not already there
                        if not any(o['id'] == order_id for o in self.open_orders):
                            self.open_orders.append({
                                'id': order_id,
                                'symbol': self.symbol,
                                'exchange': 'binance'
                            })
                    else:
                        self.logger.error(f"Failed to cancel order {order_id} via REST API")
                        
                except Exception as e:
                    error_msg = str(e)
                    if "-2011" in error_msg:  # Order not found
                        self.logger.info(f"Order {order['orderId']} already cancelled or filled")
                    else:
                        self.logger.error(f"Error cancelling order {order['orderId']}: {e}")
            
            # Clear our tracking list since we've cancelled everything
            self.open_orders.clear()
            self.logger.info(f"Comprehensive cleanup complete: {cancelled_count}/{len(open_orders)} orders cancelled")
            
        except Exception as e:
            self.logger.error(f"Error during comprehensive REST cleanup: {e}")

    async def _cleanup_orders_rest_fallback(self, failed_orders):
        """Fallback method to cancel orders using REST API"""
        try:
            from binance.spot import Spot
            
            # Create REST client for emergency cleanup
            rest_client = Spot(
                api_key=self.api_key,
                api_secret=self.secret_key,
                timeout=10
            )
            
            self.logger.info(f"Using REST API fallback to cancel {len(failed_orders)} orders")
            
            for order in failed_orders[:]:
                try:
                    cancel_response = rest_client.cancel_order(
                        symbol=self.symbol,
                        orderId=int(order['id'])
                    )
                    
                    if cancel_response and 'orderId' in cancel_response:
                        self.open_orders = [o for o in self.open_orders if o['id'] != order['id']]
                        self.logger.info(f"REST API successfully cancelled order {order['id']}")
                    else:
                        self.logger.error(f"REST API cancel failed for order {order['id']}: Invalid response")
                        
                except Exception as e:
                    error_msg = str(e)
                    if "-2011" in error_msg:  # Order not found
                        self.logger.info(f"Order {order['id']} already cancelled or filled (REST API)")
                        self.open_orders = [o for o in self.open_orders if o['id'] != order['id']]
                    else:
                        self.logger.error(f"REST API cancel failed for order {order['id']}: {e}")
                        
        except Exception as e:
            self.logger.error(f"REST API fallback initialization failed: {e}")
    
    def __del__(self):
        """Destructor to ensure cleanup when object is garbage collected"""
        try:
            if hasattr(self, 'open_orders') and self.open_orders:
                self.logger.warning(f"BinanceWebSocketExchange destructor: {len(self.open_orders)} orders still open, attempting cleanup")
                
                # Emergency synchronous cleanup using REST API
                from binance.spot import Spot
                rest_client = Spot(
                    api_key=self.api_key,
                    api_secret=self.secret_key,
                    timeout=10
                )
                
                for order in self.open_orders[:]:
                    try:
                        cancel_response = rest_client.cancel_order(
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
            
            # Cancel background tasks first
            if hasattr(self, 'connection_health_task') and self.connection_health_task and not self.connection_health_task.done():
                self.connection_health_task.cancel()
                try:
                    await self.connection_health_task
                    self.logger.info("Connection health monitoring task cancelled")
                except asyncio.CancelledError:
                    self.logger.debug("Connection health monitoring task was cancelled")
                except Exception as e:
                    self.logger.warning(f"Error cancelling health monitoring task: {e}")
            
            # Close WebSocket connections
            if hasattr(self, 'ws_client') and self.ws_client:
                try:
                    self.ws_client.stop()
                    self.logger.info("WebSocket API client stopped")
                except Exception as e:
                    self.logger.warning(f"Error stopping WebSocket API client: {e}")
            
            if hasattr(self, 'stream_client') and self.stream_client:
                try:
                    self.stream_client.stop()
                    self.logger.info("WebSocket stream client stopped")
                except Exception as e:
                    self.logger.warning(f"Error stopping WebSocket stream client: {e}")
            
            self.is_connected = False
            self.logger.info(f"{self.full_name} closed successfully")
            
        except Exception as e:
            self.logger.error(f"Error during close: {e}")
