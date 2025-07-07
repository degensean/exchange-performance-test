import os
from typing import List
from .base_exchange import BaseExchange
from .binance_exchange import BinanceExchange
from .hyperliquid_exchange import HyperliquidExchange


class ExchangeFactory:
    """Factory class for creating exchange instances"""
    
    @staticmethod
    def create_exchanges() -> List[BaseExchange]:
        """Create and return list of configured exchange instances"""
        exchanges = []
        
        # Binance
        binance_key = os.getenv("BINANCE_API_KEY")
        binance_secret = os.getenv("BINANCE_SECRET_KEY")
        if binance_key and binance_secret:
            exchanges.append(BinanceExchange(binance_key, binance_secret))
        
        # Hyperliquid
        hl_address = os.getenv("HYPERLIQUID_API_WALLET_ADDRESS")
        hl_private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY")
        if hl_address and hl_private_key:
            exchanges.append(HyperliquidExchange(hl_address, hl_private_key))
        
        return exchanges
