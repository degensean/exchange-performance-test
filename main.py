#!/usr/bin/env python3
"""
Exchange Performance Testing Framework

A modular framework for testing latency across multiple cryptocurrency exchanges.
Supports Binance and Hyperliquid with extensible architecture for adding more exchanges.

Usage:
    python main_modular.py [--duration SECONDS]

    Options:
        --duration SECONDS    Test duration in seconds (default: unlimited)

Configuration:
    Set environment variables in .env file:
    - BINANCE_API_KEY, BINANCE_SECRET_KEY for Binance testing
    - HYPERLIQUID_API_WALLET_ADDRESS, HYPERLIQUID_PRIVATE_KEY for Hyperliquid testing
    - LOG_LEVEL for logging verbosity (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - LOG_TO_FILE to enable file logging (true/false)
"""

import asyncio
import argparse
from dotenv import load_dotenv
from src.performance_tester import PerformanceTester

# Load environment variables
load_dotenv()


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Exchange Performance Testing Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python main_modular.py                 # Run unlimited time
    python main_modular.py --duration 60   # Run for 60 seconds
    python main_modular.py --no-flicker    # Force compatibility mode for remote terminals
        """
    )
    
    parser.add_argument(
        '--duration',
        type=int,
        default=None,
        help='Test duration in seconds (default: unlimited - run until stopped with Ctrl+C)'
    )
    
    parser.add_argument(
        '--no-flicker',
        action='store_true',
        help='Force compatibility mode for remote terminals to reduce flickering'
    )
    
    return parser.parse_args()


async def main():
    """Main entry point for the performance testing framework"""
    # Parse command line arguments
    args = parse_arguments()
    
    # Create performance tester with specified or default duration
    tester = PerformanceTester(duration_seconds=args.duration, force_compatibility_mode=args.no_flicker)
    
    # Run the performance test
    await tester.run_test()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown requested by user...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Ensure all tasks are cancelled on exit
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
        except:
            pass
