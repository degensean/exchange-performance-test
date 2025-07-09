#!/usr/bin/env python3
"""
Simple test to verify that our message handling integration works
"""

import asyncio
import json
import time
import os
from dotenv import load_dotenv
from binance.websocket.spot.websocket_api import SpotWebsocketAPIClient

# Load environment variables
load_dotenv()

# Global variable to store responses for analysis
responses = {}

def on_message(ws, message):
    """Message handler for debugging order responses"""
    try:
        if isinstance(message, str):
            data = json.loads(message)
        else:
            data = message
        
        print(f"📨 RECEIVED: {json.dumps(data, indent=2)}")
        
        # Store responses by ID for later analysis
        if 'id' in data:
            responses[data['id']] = data
            
    except Exception as e:
        print(f"❌ Message parse error: {e}")

async def test_simple_get_orders():
    """Simple test to verify WebSocket get orders works"""
    api_key = os.getenv('BINANCE_API_KEY')
    secret_key = os.getenv('BINANCE_SECRET_KEY')
    
    if not api_key or not secret_key:
        print("❌ Missing API keys in .env file")
        return
    
    print("🔌 Creating WebSocket API client...")
    
    ws_client = SpotWebsocketAPIClient(
        api_key=api_key,
        api_secret=secret_key,
        stream_url="wss://ws-api.binance.com:443/ws-api/v3",
        timeout=30,
        on_message=on_message
    )
    
    print("📋 Testing get open orders...")
    
    try:
        # Get open orders
        response = ws_client.get_open_orders(
            id="test_get_orders",
            symbol="BTCUSDT"
        )
        print(f"✅ Get orders request sent: {response}")
        
        # Wait for response
        print("⏳ Waiting for response...")
        await asyncio.sleep(5)
        
        # Check if we got a response
        if "test_get_orders" in responses:
            response_data = responses["test_get_orders"]
            print(f"✅ Response received: {response_data}")
            if response_data.get('status') == 200:
                orders = response_data.get('result', [])
                print(f"📦 Found {len(orders)} open orders")
            else:
                print(f"⚠️ Error response: {response_data}")
        else:
            print("❌ No response received")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
    finally:
        print("🛑 Stopping WebSocket client...")
        try:
            ws_client.stop()
        except Exception as e:
            print(f"⚠️ Stop error: {e}")

if __name__ == "__main__":
    asyncio.run(test_simple_get_orders())
