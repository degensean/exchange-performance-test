"""
Configuration settings for the exchange performance testing framework
"""

# Test Configuration
DEFAULT_TEST_DURATION = None  # Unlimited time (None = run until stopped)
TEST_INTERVAL_MIN = 0.5      # Minimum seconds between tests
TEST_INTERVAL_MAX = 1.0      # Maximum seconds between tests
ORDER_SIZE_BTC = 0.0001      # BTC order size for testing (further reduced to avoid insufficient funds errors)
MARKET_OFFSET = 0.95         # Place orders at 95% of market price

# Exchange-specific Configuration
BINANCE_CONFIG = {
    'symbol': 'BTCUSDT',
    'base_url': 'https://api.binance.com',
    'ws_url': 'wss://stream.binance.com:9443/ws/',
    'api_endpoint': '/api/v3/order',
    'tick_size_high': 0.10,     # For prices >= 1000
    'tick_size_low': 0.01,      # For prices < 1000
    'tick_threshold': 1000,
    'quantity_precision': 6,    # 6 decimal places for spot (0.000001)
    'price_precision': 2        # 2 decimal places for spot prices
}

HYPERLIQUID_CONFIG = {
    'asset': 'BTC',
    'tick_size': 1.0,           # $1 tick size for BTC
    'default_tick_size': 0.01   # For other assets
}

# Display Configuration
REFRESH_RATE = 2  # Table refresh rate in Hz (reduced for smoother updates)
DECIMAL_PLACES = 4  # Precision for latency display

# API Mode Configuration
ENABLE_REST_API = True      # Enable REST API testing
ENABLE_WEBSOCKET_API = True # Enable WebSocket API testing
WEBSOCKET_TIMEOUT = 30.0    # WebSocket connection timeout in seconds (increased from 10s)
WEBSOCKET_PING_INTERVAL = 60.0  # WebSocket ping interval in seconds (increased from 20s)

# Connection Recovery Configuration
MAX_RECONNECT_ATTEMPTS = 3   # Maximum number of reconnection attempts
RECONNECT_BASE_DELAY = 1.0   # Base delay between reconnection attempts (exponential backoff)
CONNECTION_HEALTH_CHECK_INTERVAL = 120.0  # Interval to check connection health (seconds)
