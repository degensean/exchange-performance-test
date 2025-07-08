# Exchange Performance Testing Framework

A modular, extensible framework for testing latency across multiple cryptocurrency exchanges.

![Performance Test Screenshot](assets/images/screenshot.png)

## 🏗️ **Modular Architecture**

```
src/
├── __init__.py              # Package initialization
├── models.py                # Data models (LatencyData)
├── config.py                # Configuration settings
├── base_exchange.py         # Abstract exchange interface
├── binance_exchange.py      # Binance implementation
├── hyperliquid_exchange.py  # Hyperliquid implementation
├── exchange_factory.py      # Exchange factory pattern
└── performance_tester.py    # Main testing orchestrator

main_modular.py              # Entry point for modular version
```

## 🚀 **Features**

- **Multi-Exchange**: Supports Binance and Hyperliquid simultaneously
- **Dual API Support**: Tests both REST and WebSocket APIs for comprehensive latency comparison
- **Robust Cleanup**: Automatic order cancellation and cleanup on exit
- **Safe Order Placement**: Orders placed 5% below market to avoid execution
- **Rich Display**: Live updating statistics table with color coding
- **Comprehensive Logging**: Detailed failure reason tracking and debugging information
- **Remote Terminal Compatibility**: Automatic detection and adjustment for SSH/remote connections

## 📊 **Metrics Tracked**

- **Orderbook Latency**: Time to retrieve real-time orderbook data
- **Order Placement**: Time to place limit orders  
- **Order Cancellation**: Time to cancel orders
- **Failure Rates**: Percentage of failed requests for each operation type
- **Advanced Statistics**: Min, Max, Mean, Median, Standard Deviation, P95, P99, Count, and Failure Rate
- **Failure Reasons**: Detailed logging of why requests fail (timeouts, connection errors, API errors, etc.)

## 🔧 **Configuration**

Edit `src/config.py` to customize:

```python
# Test Configuration
DEFAULT_TEST_DURATION = None  # Unlimited time (None = run until stopped)
ORDER_SIZE_BTC = 0.001         # 0.001 BTC orders
MARKET_OFFSET = 0.95           # Place orders 5% below market

# Binance Configuration
BINANCE_CONFIG = {
    'symbol': 'BTCUSDT',
    # ... additional configuration
}
# Display Configuration
REFRESH_RATE = 2               # Updates per second
DECIMAL_PLACES = 4             # Precision for latency display

# API Mode Configuration
ENABLE_REST_API = True         # Enable REST API testing
ENABLE_WEBSOCKET_API = True    # Enable WebSocket API testing
WEBSOCKET_TIMEOUT = 10.0       # WebSocket connection timeout
WEBSOCKET_PING_INTERVAL = 20.0 # WebSocket ping interval
```

### **Binance Account Types**

The framework supports Binance Spot trading:

- **`spot`**: Binance Spot trading (https://api.binance.com)

### **Logging Configuration**

The framework provides comprehensive logging with configurable levels and output options:

```bash
# Logging Configuration
LOG_LEVEL=INFO           # DEBUG, INFO, WARNING, ERROR, CRITICAL  
LOG_TO_FILE=true         # true/false - whether to log to file
LOG_DIR=logs             # directory for log files
```

**Log Levels:**
- **DEBUG**: Detailed information for debugging (request/response details, timing)
- **INFO**: General information about application flow and status
- **WARNING**: Warning messages for non-critical issues
- **ERROR**: Error messages for failures with stack traces
- **CRITICAL**: Critical errors that might cause application shutdown

**Failure Reason Logging:**
- Connection timeouts and network errors
- API authentication failures  
- Invalid response formats
- Rate limiting and throttling
- Order placement/cancellation failures
- WebSocket connection issues

## 📈 **Advanced Statistical Metrics**

The framework provides comprehensive statistical analysis for performance assessment:

### **📏 Central Tendency**
- **Mean**: Average latency across all requests
- **Median**: Middle value when latencies are sorted (P50)

### **📊 Variability Measures**
- **Standard Deviation**: Measures consistency of performance (lower = more consistent)
- **Min/Max**: Best and worst case performance

### **🎯 Percentile Analysis**
- **P95 (95th Percentile)**: 95% of requests complete faster than this time
- **P99 (99th Percentile)**: 99% of requests complete faster than this time

### **🚦 Performance Interpretation**
- **Low Std Dev + Low P99**: Excellent, consistent performance
- **High Std Dev**: Variable performance, investigate network/load issues
- **High P99 vs P95**: Occasional severe outliers, potential timeouts

## 🌟 **Usage**

### Command Line Options
```bash
# Run unlimited time (default)
python main_modular.py

# Run for specific duration
python main_modular.py --duration 60    # 60 seconds

# Force compatibility mode for remote terminals (reduces flickering)
python main_modular.py --no-flicker

# Combine options
python main_modular.py --duration 30 --no-flicker

# Show help
python main_modular.py --help
```

### **Remote Terminal Compatibility**

If you experience flickering when running on remote Linux systems through Windows Terminal or SSH, the framework automatically detects remote environments and adjusts settings. For persistent flickering issues, use the `--no-flicker` flag:

```bash
python main_modular.py --no-flicker
```

This enables enhanced compatibility mode with:
- Reduced refresh rate (0.5Hz instead of 2Hz)
- Modified ANSI escape sequence handling
- Better buffer management for remote connections

## 🔄 **REST vs WebSocket API Comparison**

The framework tests both REST and WebSocket APIs to provide comprehensive latency analysis:

### **REST API Characteristics**
- ✅ **Reliable**: Each request gets a definitive response
- ✅ **Simple**: Easy error handling and debugging
- ✅ **Universal**: Widely supported across all operations
- ❌ **Higher Latency**: HTTP request/response overhead
- ❌ **Rate Limited**: Subject to stricter API rate limits

### **WebSocket API Characteristics**
- ✅ **Lower Latency**: Persistent connection, minimal overhead
- ✅ **Real-time**: Ideal for streaming market data
- ✅ **Efficient**: Better bandwidth utilization
- ❌ **Complex**: Connection management and reconnection logic
- ❌ **Limited Operations**: Not all operations support WebSocket

### **API Mode Configuration**

Control which APIs to test via `src/config.py`:

```python
ENABLE_REST_API = True      # Test REST APIs
ENABLE_WEBSOCKET_API = True # Test WebSocket APIs
```

**Expected Results:**
- **Market Data**: WebSocket typically 20-50% faster than REST
- **Order Operations**: Mixed results depending on exchange implementation
- **Binance**: WebSocket excellent for market data, REST for orders
- **Hyperliquid**: WebSocket for market data, REST for order operations

### Quick Start
```bash
# Copy environment variables
cp env.example .env

# Edit .env with your API credentials
# BINANCE_API_KEY=your_api_key
# BINANCE_SECRET_KEY=your_secret_key  
# LOG_LEVEL=INFO                  # DEBUG for detailed logging

# Run the modular version
python main_modular.py
```

### Adding New Exchanges

1. **Create Exchange Class**: Inherit from `BaseExchange`
2. **Implement Required Methods**:
   - `test_orderbook_latency()`
   - `test_order_latency()`
   - `_extract_bids_asks()`
   - `cleanup_open_orders()`
3. **Add to Factory**: Update `ExchangeFactory.create_exchanges()`
4. **Configure**: Add exchange config to `config.py`