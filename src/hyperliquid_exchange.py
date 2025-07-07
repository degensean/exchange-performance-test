import time
import eth_account
from eth_account.signers.local import LocalAccount
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from .base_exchange import BaseExchange
from .config import HYPERLIQUID_CONFIG, ORDER_SIZE_BTC, MARKET_OFFSET


class HyperliquidExchange(BaseExchange):
    """Hyperliquid exchange implementation"""
    
    def __init__(self, wallet_address: str, private_key: str, asset: str | None = None):
        super().__init__("Hyperliquid")
        self.wallet_address = wallet_address
        self.private_key = private_key
        self.asset = asset or HYPERLIQUID_CONFIG['asset']
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        
        # Create LocalAccount for signing
        self.account: LocalAccount = eth_account.Account.from_key(private_key)
        self.exchange = Exchange(self.account, constants.MAINNET_API_URL, account_address=wallet_address)

    def _get_tick_size(self, asset: str = "BTC") -> float:
        """Get the correct tick size for Hyperliquid assets"""
        if asset == "BTC":
            return HYPERLIQUID_CONFIG['tick_size']
        return HYPERLIQUID_CONFIG['default_tick_size']

    def _round_to_tick_size(self, price: float, asset: str = "BTC") -> float:
        """Round price to the nearest valid tick size"""
        tick_size = self._get_tick_size(asset)
        return round(price / tick_size) * tick_size

    def _extract_bids_asks(self, orderbook_data):
        """Extract bids and asks from Hyperliquid orderbook data"""
        try:
            if isinstance(orderbook_data, dict) and 'levels' in orderbook_data:
                levels = orderbook_data['levels']
                if isinstance(levels, list) and len(levels) == 2:
                    bids_data, asks_data = levels[0], levels[1]
                    
                    bids = []
                    asks = []
                    
                    for bid in bids_data:
                        if isinstance(bid, dict) and 'px' in bid and 'sz' in bid:
                            bids.append([bid['px'], bid['sz']])
                    
                    for ask in asks_data:
                        if isinstance(ask, dict) and 'px' in ask and 'sz' in ask:
                            asks.append([ask['px'], ask['sz']])
                    
                    return bids, asks
        except Exception:
            pass
        return None, None

    async def test_orderbook_latency(self) -> None:
        """Test Hyperliquid orderbook latency"""
        self.failure_data.orderbook_total += 1
        try:
            start_time = time.time()
            l2_data = self.info.l2_snapshot(self.asset)
            latency = time.time() - start_time
            
            if l2_data:
                self.latest_orderbook = l2_data
                self.latency_data.orderbook.append(latency)
                self.latest_price = self.get_mid_price_from_orderbook()
            else:
                self.failure_data.orderbook_failures += 1
        except Exception:
            self.failure_data.orderbook_failures += 1
    
    async def test_order_latency(self) -> None:
        """Test Hyperliquid order placement and cancellation latency"""
        if not self.exchange or not self.latest_price:
            return
        
        # Place order 5% below market to avoid execution
        raw_price = self.latest_price * MARKET_OFFSET
        price = self._round_to_tick_size(raw_price, self.asset)
        
        self.failure_data.place_order_total += 1
        try:
            # Place order
            start_time = time.time()
            result = self.exchange.order(
                name=self.asset,
                is_buy=True,
                sz=ORDER_SIZE_BTC,
                limit_px=price,
                order_type={"limit": {"tif": "Gtc"}},
                reduce_only=False
            )
            
            if result and result.get("status") == "ok":
                place_latency = time.time() - start_time
                self.latency_data.place_order.append(place_latency)
                
                # Try to cancel order immediately
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                if statuses and "resting" in statuses[0]:
                    order_id = statuses[0]["resting"]["oid"]
                    
                    # Track for cleanup
                    self.open_orders.append({
                        'id': order_id,
                        'asset': self.asset,
                        'exchange': 'hyperliquid'
                    })
                    
                    # Cancel order
                    self.failure_data.cancel_order_total += 1
                    start_time = time.time()
                    cancel_result = self.exchange.cancel(self.asset, order_id)
                    cancel_latency = time.time() - start_time
                    
                    if cancel_result and cancel_result.get("status") == "ok":
                        self.latency_data.cancel_order.append(cancel_latency)
                        self.open_orders = [o for o in self.open_orders if o['id'] != order_id]
                    else:
                        self.failure_data.cancel_order_failures += 1
                else:
                    self.failure_data.place_order_failures += 1
            else:
                self.failure_data.place_order_failures += 1
            
        except Exception:
            self.failure_data.place_order_failures += 1
    
    async def cleanup_open_orders(self):
        """Cancel all open Hyperliquid orders"""
        if not self.open_orders:
            return
        
        for order in self.open_orders[:]:
            try:
                result = self.exchange.cancel(order['asset'], order['id'])
                if result and result.get("status") == "ok":
                    self.open_orders.remove(order)
            except Exception:
                pass
