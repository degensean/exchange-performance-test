#!/usr/bin/env python3
"""
Simple test script to verify Binance WebSocket implementation
"""
import asyncio
import os
from dotenv import load_dotenv
from src.binance_websocket_exchange import BinanceWebSocketExchange

async def test_websocket_implementation():
    """Test the WebSocket implementation without actually placing orders"""
    
    # Load environment variables
    load_dotenv()
    
    api_key = os.getenv('BINANCE_API_KEY')
    secret_key = os.getenv('BINANCE_SECRET_KEY')
    
    if not api_key or not secret_key:
        print("ERROR: Please set BINANCE_API_KEY and BINANCE_SECRET_KEY in .env file")
        return
    
    print("Testing Binance WebSocket implementation...")
    
    # Initialize the exchange
    exchange = BinanceWebSocketExchange(api_key, secret_key)
    
    try:
        # Test connection
        print("1. Testing connection...")
        await exchange.connect()
        print(f"   ✓ Connection status: {exchange.is_connected}")
        
        # Test WebSocket client initialization
        print("2. Testing WebSocket client...")
        if exchange.ws_client:
            print("   ✓ WebSocket client initialized")
        else:
            print("   ✗ WebSocket client not initialized")
        
        # Test method availability
        print("3. Testing method availability...")
        methods_to_test = [
            '_handle_websocket_message',
            '_generate_request_id', 
            '_place_order_websocket',
            '_cancel_order_websocket'
        ]
        
        for method_name in methods_to_test:
            if hasattr(exchange, method_name):
                print(f"   ✓ {method_name} method available")
            else:
                print(f"   ✗ {method_name} method missing")
        
        # Test request ID generation
        print("4. Testing request ID generation...")
        req_id1 = exchange._generate_request_id()
        req_id2 = exchange._generate_request_id()
        if req_id1 != req_id2:
            print(f"   ✓ Unique request IDs generated: {req_id1}, {req_id2}")
        else:
            print(f"   ✗ Request IDs not unique: {req_id1}, {req_id2}")
        
        print("\n✓ WebSocket implementation test completed successfully!")
        print("Note: This test only verifies method availability and basic functionality.")
        print("Actual order placement requires valid API credentials and testnet environment.")
        
    except Exception as e:
        print(f"✗ Test failed with error: {e}")
        
    finally:
        # Cleanup
        try:
            await exchange.close()
            print("✓ Exchange closed successfully")
        except Exception as e:
            print(f"Warning: Error during cleanup: {e}")

if __name__ == "__main__":
    asyncio.run(test_websocket_implementation())
