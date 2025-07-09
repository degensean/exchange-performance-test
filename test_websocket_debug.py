#!/usr/bin/env python

import asyncio
import json
import logging
import time
from binance.websocket.spot.websocket_api import SpotWebsocketAPIClient
from binance.lib.utils import config_logging

# Set up logging
config_logging(logging, logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables
import os
from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_SECRET_KEY')

def on_close(_):
    logger.info("WebSocket connection closed")

def message_handler(_, message):
    logger.info(f"Received message: {message}")

def test_websocket_connection():
    """Test basic WebSocket connection and message handling"""
    logger.info("Testing WebSocket connection...")
    
    try:
        # Create WebSocket client
        client = SpotWebsocketAPIClient(
            stream_url="wss://ws-api.binance.com:443/ws-api/v3",
            api_key=api_key,
            api_secret=api_secret,
            on_message=message_handler,
            on_close=on_close,
        )
        
        logger.info("WebSocket client created, attempting to place test order...")
        
        # Place a test order (this will likely fail due to insufficient funds, but we should get a response)
        client.new_order(
            id="test_123",
            symbol="BTCUSDT",
            side="BUY",
            type="LIMIT",
            timeInForce="GTC",
            quantity="0.001",
            price="30000",
        )
        
        logger.info("Order placed, waiting for response...")
        time.sleep(5)
        
        logger.info("Stopping WebSocket client...")
        client.stop()
        
        logger.info("Test completed")
        
    except Exception as e:
        logger.error(f"Test failed: {e}")

if __name__ == "__main__":
    test_websocket_connection()
