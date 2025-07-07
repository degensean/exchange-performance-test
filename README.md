# Exchange Performance Testing Framework

A modular, extensible framework for testing latency across multiple cryptocurrency exchanges.

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
- **Robust Cleanup**: Automatic order cancellation and cleanup on exit
- **Safe Order Placement**: Orders placed 5% below market to avoid execution
- **Rich Display**: Live updating statistics table with color coding

## 📊 **Metrics Tracked**

- **Orderbook Latency**: Time to retrieve real-time orderbook data
- **Order Placement**: Time to place limit orders
- **Order Cancellation**: Time to cancel orders
- **Statistics**: Min, Max, Average, and Count for each metric

## 🔧 **Configuration**

Edit `src/config.py` to customize:

```python
# Test Configuration
DEFAULT_TEST_DURATION = 600  # 10 minutes
ORDER_SIZE_BTC = 0.001       # 0.001 BTC orders
MARKET_OFFSET = 0.95         # Place orders 5% below market

# Display Configuration
REFRESH_RATE = 2             # Updates per second
DECIMAL_PLACES = 4           # Precision for latency display
```

## 🌟 **Usage**

### Quick Start
```bash
# Copy environment variables
cp env.example .env
# Edit .env with your API credentials
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