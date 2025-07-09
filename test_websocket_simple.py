#!/usr/bin/env python3
"""
Simple WebSocket API test to diagnose connection issues
"""

import asyncio
import json
import time
from dotenv import load_dotenv
import os
from binance.websocket.spot.websocket_api import SpotWebsocketAPIClient

# Load environment variables
load_dotenv()

def on_message(ws, message):
    """Simple message handler for debugging"""
    try:
        if isinstance(message, str):
            data = json.loads(message)
        else:
            data = message
        print(f"📨 RECEIVED: {data}")
    except Exception as e:
        print(f"❌ Message parse error: {e}")

async def test_simple_websocket():
    """Test basic WebSocket API functionality"""
    api_key = os.getenv('BINANCE_API_KEY')
    secret_key = os.getenv('BINANCE_SECRET_KEY')
    
    if not api_key or not secret_key:
        print("❌ Missing API keys in .env file")
        return
    
    print("🔌 Creating WebSocket API client...")
    
    # Test with official binance-connector
    ws_client = SpotWebsocketAPIClient(
        api_key=api_key,
        api_secret=secret_key,
        stream_url="wss://ws-api.binance.com:443/ws-api/v3",
        timeout=10,
        on_message=on_message
    )
    
    print("📡 Testing simple account info request...")
    
    # Try a simple account info request (doesn't place orders)
    try:
        response = ws_client.account()
        print(f"✅ Account request sent: {response}")
        
        # Wait a bit for response
        await asyncio.sleep(5)
        
    except Exception as e:
        print(f"❌ Account request failed: {e}")
    
    print("🔄 Testing ping request...")
    try:
        response = ws_client.ping()
        print(f"✅ Ping request sent: {response}")
        
        # Wait a bit for response
        await asyncio.sleep(3)
        
    except Exception as e:
        print(f"❌ Ping request failed: {e}")
    
    print("🛑 Stopping WebSocket client...")
    try:
        ws_client.stop()
    except Exception as e:
        print(f"⚠️ Stop error: {e}")

if __name__ == "__main__":
    asyncio.run(test_simple_websocket())
