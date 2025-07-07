import os
from typing import List
from .base_exchange import BaseExchange
from .binance_exchange import BinanceExchange
from .hyperliquid_exchange import HyperliquidExchange
from .config import BINANCE_CONFIG


class ExchangeFactory:
    """Factory class for creating exchange instances"""
    
    @staticmethod
    def create_exchanges() -> List[BaseExchange]:
        """Create and return list of configured exchange instances"""
        exchanges = []
        
        # Binance
        binance_key = os.getenv("BINANCE_API_KEY")
        binance_secret = os.getenv("BINANCE_SECRET_KEY")
        binance_account_type = os.getenv("BINANCE_ACCOUNT_TYPE", BINANCE_CONFIG['account_type'])
        
        if binance_key and binance_secret:
            exchanges.append(BinanceExchange(
                binance_key, 
                binance_secret,
                account_type=binance_account_type
            ))
        
        # Hyperliquid
        hl_address = os.getenv("HYPERLIQUID_API_WALLET_ADDRESS")
        hl_private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY")
        if hl_address and hl_private_key:
            exchanges.append(HyperliquidExchange(hl_address, hl_private_key))
        
        return exchanges
