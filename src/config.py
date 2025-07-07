"""
Configuration settings for the exchange performance testing framework
"""

# Test Configuration
DEFAULT_TEST_DURATION = None  # Unlimited time (None = run until stopped)
TEST_INTERVAL_MIN = 0.5      # Minimum seconds between tests
TEST_INTERVAL_MAX = 1.0      # Maximum seconds between tests
ORDER_SIZE_BTC = 0.001       # BTC order size for testing
MARKET_OFFSET = 0.95         # Place orders at 95% of market price

# Exchange-specific Configuration
BINANCE_CONFIG = {
    'symbol': 'BTCUSDT',
    'base_url': 'https://papi.binance.com',
    'ws_url': 'wss://fstream.binance.com/ws/',
    'tick_size_high': 0.10,     # For prices >= 1000
    'tick_size_low': 0.01,      # For prices < 1000
    'tick_threshold': 1000
}

HYPERLIQUID_CONFIG = {
    'asset': 'BTC',
    'tick_size': 1.0,           # $1 tick size for BTC
    'default_tick_size': 0.01   # For other assets
}

# Display Configuration
REFRESH_RATE = 2  # Table refresh rate in Hz
DECIMAL_PLACES = 4  # Precision for latency display
