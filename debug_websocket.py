#!/usr/bin/env python3
"""
Debug WebSocket connection issues
"""

import asyncio
import time
from dotenv import load_dotenv
import os
from src.binance_websocket_exchange import BinanceWebSocketExchange

# Load environment variables
load_dotenv()

async def debug_websocket():
    """Debug WebSocket connection and order placement"""
    api_key = os.getenv('BINANCE_API_KEY')
    secret_key = os.getenv('BINANCE_SECRET_KEY')
    
    if not api_key or not secret_key:
        print("Missing API keys in .env file")
        return
    
    print("Creating WebSocket exchange...")
    exchange = BinanceWebSocketExchange(api_key, secret_key)
    
    print("Testing WebSocket connection...")
    try:
        # Test connection
        print(f"Initial connection status: {exchange.is_connected}")
        
        # Try to connect
        await exchange._connect_websocket()
        print(f"After connect attempt: {exchange.is_connected}")
        
        # Try a simple test - get account info or ping
        print("Testing basic WebSocket operation...")
        await exchange._test_connection()
        
        # Test order placement with debug
        print("Testing order placement (this might timeout)...")
        start_time = time.time()
        
        try:
            await exchange.test_order_latency()
            print(f"Order test completed in {time.time() - start_time:.2f}s")
        except Exception as e:
            print(f"Order test failed after {time.time() - start_time:.2f}s: {e}")
            
    except Exception as e:
        print(f"WebSocket test failed: {e}")
    finally:
        print("Cleaning up...")
        await exchange.cleanup_open_orders()

if __name__ == "__main__":
    asyncio.run(debug_websocket())
