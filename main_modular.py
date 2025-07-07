#!/usr/bin/env python3
"""
Exchange Performance Testing Framework

A modular framework for testing latency across multiple cryptocurrency exchanges.
Supports Binance and Hyperliquid with extensible architecture for adding more exchanges.

Usage:
    python main_modular.py

Configuration:
    Set environment variables in .env file:
    - BINANCE_API_KEY, BINANCE_SECRET_KEY for Binance testing
    - HYPERLIQUID_API_WALLET_ADDRESS, HYPERLIQUID_PRIVATE_KEY for Hyperliquid testing
"""

import asyncio
from dotenv import load_dotenv
from src.performance_tester import PerformanceTester

# Load environment variables
load_dotenv()


async def main():
    """Main entry point for the performance testing framework"""
    # Create performance tester with default duration from config
    tester = PerformanceTester()
    
    # Run the performance test
    await tester.run_test()


if __name__ == "__main__":
    asyncio.run(main())
