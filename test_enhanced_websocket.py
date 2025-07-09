#!/usr/bin/env python3
"""
Enhanced WebSocket API test demonstrating the improved functionality

This script demonstrates the enhanced WebSocket functionality that has been
integrated into the main BinanceWebSocketExchange class from test_websocket_order.py:

Features now available:
- ✅ Enhanced cancel all orders operation via WebSocket
- ✅ Get open orders via WebSocket API
- ✅ Multiple order placement with proper error handling
- ✅ Improved cleanup operations with bulk cancellation
- ✅ Better response correlation and timeout handling

The improvements include:
1. cancel_all_orders_websocket() - Bulk cancel operation
2. _get_open_orders_websocket() - Query open orders
3. place_multiple_orders_websocket() - Place multiple orders efficiently
4. Enhanced cleanup_open_orders() - Uses bulk operations first, then fallback
"""

import asyncio
import os
from dotenv import load_dotenv
from src.binance_websocket_exchange import BinanceWebSocketExchange

async def test_enhanced_websocket_functionality():
    """Test the enhanced WebSocket functionality integrated from test_websocket_order.py"""
    
    # Load environment variables
    load_dotenv()
    
    api_key = os.getenv('BINANCE_API_KEY')
    secret_key = os.getenv('BINANCE_SECRET_KEY')
    
    if not api_key or not secret_key:
        print("❌ ERROR: Please set BINANCE_API_KEY and BINANCE_SECRET_KEY in .env file")
        return
    
    print("🚀 Testing Enhanced Binance WebSocket Implementation...")
    
    # Initialize the enhanced exchange
    exchange = BinanceWebSocketExchange(api_key, secret_key)
    
    try:
        # Test connection
        print("\n1. 🔌 Testing connection...")
        await exchange.connect()
        print(f"   ✅ Connection status: {exchange.is_connected}")
        
        # Test get open orders functionality
        print("\n2. 📋 Testing get open orders via WebSocket...")
        try:
            # Add some debugging info
            print(f"   🔍 WebSocket client status: {exchange.ws_client}")
            print(f"   🔍 Is connected: {exchange.is_connected}")
            print(f"   🔍 Pending requests before: {len(exchange.pending_requests)}")
            
            open_orders = await exchange._get_open_orders_websocket()
            print(f"   ✅ Found {len(open_orders)} open orders")
            for order in open_orders:
                print(f"   📦 Order: {order.get('orderId')} - {order.get('symbol')} {order.get('side')} {order.get('origQty')} @ {order.get('price')}")
        except Exception as e:
            print(f"   ⚠️ Get open orders test: {e}")
            print(f"   🔍 Pending requests after error: {len(exchange.pending_requests)}")
        
        # Test multiple order placement (if you want to test this, uncomment below)
        print("\n3. 🛒 Testing multiple order placement (demonstration)...")
        sample_orders = [
            {
                'side': 'BUY',
                'quantity': 0.0001,
                'price': 90000.00,
                'timeInForce': 'GTC'
            },
            {
                'side': 'BUY', 
                'quantity': 0.0001,
                'price': 89900.00,
                'timeInForce': 'GTC'
            }
        ]
        
        print(f"   📝 Would place {len(sample_orders)} orders (commented out for safety)")
        print("   💡 Uncomment the code below to actually test order placement")
        
        # Uncomment below to actually test order placement
        # try:
        #     result = await exchange.place_multiple_orders_websocket(sample_orders)
        #     print(f"   ✅ Placed {result['success_count']} orders, {result['failure_count']} failed")
        # except Exception as e:
        #     print(f"   ⚠️ Multiple order placement test: {e}")
        
        # Test cancel all orders functionality
        print("\n4. 🧹 Testing cancel all orders via WebSocket...")
        try:
            result = await exchange.cancel_all_orders_websocket()
            cancelled_orders = result.get('cancelled_orders', [])
            print(f"   ✅ Cancelled {len(cancelled_orders)} orders via bulk operation")
        except Exception as e:
            print(f"   ⚠️ Cancel all orders test: {e}")
        
        # Test enhanced cleanup functionality
        print("\n5. 🔧 Testing enhanced cleanup functionality...")
        try:
            await exchange.cleanup_open_orders()
            print("   ✅ Enhanced cleanup completed successfully")
        except Exception as e:
            print(f"   ⚠️ Enhanced cleanup test: {e}")
        
        print("\n✅ Enhanced WebSocket functionality test completed!")
        print("\n🎯 Summary of improvements integrated:")
        print("   • Enhanced bulk cancel all orders operation")
        print("   • WebSocket-based open orders querying")
        print("   • Multiple order placement with proper error handling")
        print("   • Improved cleanup with bulk operations and fallback")
        print("   • Better response correlation and timeout handling")
        print("\n💡 These improvements from test_websocket_order.py are now available in the main framework!")
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        
    finally:
        # Cleanup
        try:
            await exchange.close()
            print("✅ Exchange closed successfully")
        except Exception as e:
            print(f"⚠️ Warning: Error during cleanup: {e}")

if __name__ == "__main__":
    asyncio.run(test_enhanced_websocket_functionality())
