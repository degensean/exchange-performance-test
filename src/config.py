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
    'account_type': 'portfolio',  # 'spot', 'umfutures', 'portfolio'
    'base_urls': {
        'spot': 'https://api.binance.com',
        'umfutures': 'https://fapi.binance.com', 
        'portfolio': 'https://papi.binance.com'
    },
    'ws_urls': {
        'spot': 'wss://stream.binance.com:9443/ws/',
        'umfutures': 'wss://fstream.binance.com/ws/',
        'portfolio': 'wss://fstream.binance.com/ws/'
    },
    'api_endpoints': {
        'spot': '/api/v3/order',
        'umfutures': '/fapi/v1/order',
        'portfolio': '/papi/v1/um/order'
    },
    'tick_size_high': 0.10,     # For prices >= 1000
    'tick_size_low': 0.01,      # For prices < 1000
    'tick_threshold': 1000,
    'quantity_precision': {
        'spot': 6,              # 6 decimal places for spot (0.000001)
        'umfutures': 3,         # 3 decimal places for UM futures (0.001)
        'portfolio': 3          # 3 decimal places for portfolio margin (0.001)
    },
    'price_precision': {
        'spot': 2,              # 2 decimal places for spot prices
        'umfutures': 2,         # 2 decimal places for futures prices  
        'portfolio': 2          # 2 decimal places for portfolio margin prices
    }
}

HYPERLIQUID_CONFIG = {
    'asset': 'BTC',
    'tick_size': 1.0,           # $1 tick size for BTC
    'default_tick_size': 0.01   # For other assets
}

# Display Configuration
REFRESH_RATE = 5  # Table refresh rate in Hz
DECIMAL_PLACES = 4  # Precision for latency display
