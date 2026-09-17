"""Background price history collection service"""
import threading
import time
import models
from services import solana_rpc


class PriceMonitor:
    """Background service that collects price snapshots every 5-10 seconds"""

    def __init__(self, update_interval_seconds=8):
        self.interval = update_interval_seconds
        self.running = False
        self.thread = None

    def start(self):
        """Start background price collection"""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        print(f"[PriceMonitor] Started (interval: {self.interval}s)")

    def stop(self):
        """Stop background price collection"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print("[PriceMonitor] Stopped")

    def _run(self):
        """Main loop: collect prices for all known coins"""
        while self.running:
            try:
                self._collect_prices()
            except Exception as e:
                print(f"[PriceMonitor] Error: {e}")

            # Prune old data periodically (every hour)
            if int(time.time()) % 3600 == 0:
                try:
                    models.prune_old_prices(days=7)
                except:
                    pass

            time.sleep(self.interval)

    def _collect_prices(self):
        """Get latest coins and record their prices"""
        coins = models.get_latest_coins(limit=50)

        for coin in coins:
            try:
                # Calculate price from supply estimate
                price = self._estimate_price(coin)
                if price and price > 0:
                    models.record_price(
                        coin_id=coin['id'],
                        price=price,
                        market_cap=coin.get('market_cap', 0),
                        holder_count=coin.get('holder_count', 0)
                    )
            except Exception as e:
                print(f"[PriceMonitor] Failed to record price for {coin.get('name')}: {e}")

    def _estimate_price(self, coin):
        """Estimate price in USD from market cap and supply"""
        try:
            market_cap = coin.get('market_cap', 0)
            if not market_cap or market_cap <= 0:
                return 0.000001  # Use minimum price if no market cap

            supply = solana_rpc.get_token_supply(coin['token_address'])
            if not supply or supply <= 0:
                return 0.000001

            decimals = 6  # Most SPL tokens use 6 decimals
            total_tokens = supply / (10 ** decimals)

            if total_tokens <= 0:
                return 0.000001

            price = market_cap / total_tokens
            return max(price, 0.000001)  # Floor at 0.000001
        except:
            return 0.000001


# Global instance
_monitor = None


def start_monitor(interval_seconds=8):
    """Initialize and start the global price monitor"""
    global _monitor
    if _monitor is None:
        _monitor = PriceMonitor(update_interval_seconds=interval_seconds)
    _monitor.start()


def stop_monitor():
    """Stop the global price monitor"""
    global _monitor
    if _monitor:
        _monitor.stop()
