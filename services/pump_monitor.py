"""Real-time monitoring of Pump.fun for new token launches"""
import threading
import time
import urllib.request
import urllib.error
import json
import db
import models
from services.token_analyzer import TokenAnalyzer


class PumpFunMonitor:
    """Background service to monitor Pump.fun and discover new tokens"""

    def __init__(self, update_interval_seconds=15):
        self.interval = update_interval_seconds
        self.running = False
        self.thread = None
        self.last_check_time = 0
        self.seen_coins = set()
        self.analyzer = TokenAnalyzer()

    def start(self):
        """Start background monitoring in a daemon thread"""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        print(f"[PumpFunMonitor] Started (interval: {self.interval}s)")

    def stop(self):
        """Stop background monitoring"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print("[PumpFunMonitor] Stopped")

    def _run(self):
        """Main loop: fetch new coins and analyze"""
        while self.running:
            try:
                self._check_and_process()
            except Exception as e:
                print(f"[PumpFunMonitor] Error: {e}")

            time.sleep(self.interval)

    def _check_and_process(self):
        """Fetch new coins from Pump.fun and store/analyze them"""
        coins = self._fetch_pump_launches()

        if not coins:
            return

        for coin in coins:
            token_address = coin.get("token")
            if not token_address or token_address in self.seen_coins:
                continue

            # Skip coins with no market data (insufficient information)
            if coin.get("market_cap", 0) == 0 and coin.get("holders", 0) == 0:
                continue

            try:
                self.seen_coins.add(token_address)

                # Insert coin to database
                coin_id = models.insert_coin(
                    token_address=token_address,
                    name=coin.get("name"),
                    symbol=coin.get("symbol"),
                    description=coin.get("description"),
                    creator_wallet=coin.get("creator"),
                    pump_url=coin.get("url"),
                    market_cap=coin.get("market_cap"),
                    holder_count=coin.get("holders")
                )

                # Analyze immediately
                analysis = self.analyzer.analyze(token_address, pump_url=coin.get("url"))

                # Use mock data if analysis returned 0 (for demo purposes)
                holder_count = analysis.get("holder_count") or coin.get("holders", 0)
                market_cap = analysis.get("market_cap") or coin.get("market_cap", 0)

                if holder_count > 0 or market_cap > 0:
                    models.update_coin(
                        coin_id,
                        holder_count=holder_count,
                        market_cap=market_cap
                    )

                # Store analysis scores
                models.update_coin_analysis(
                    coin_id,
                    rug_pull_score=analysis.get("rug_pull_score", 0.5),
                    honeypot_score=analysis.get("honeypot_score", 0.5),
                    scam_score=analysis.get("scam_score", 0.5),
                    community_score=analysis.get("community_score", 0.5),
                    liquidity_score=analysis.get("liquidity_score", 0.5),
                    dev_wallet_percentage=analysis.get("dev_wallet_percentage"),
                    is_liquidity_locked=analysis.get("is_liquidity_locked"),
                    is_mint_renounced=analysis.get("is_mint_renounced"),
                    has_anti_whale=analysis.get("has_anti_whale"),
                    is_contract_verified=analysis.get("is_contract_verified"),
                    recommendation=analysis.get("recommendation"),
                    analysis_notes=analysis.get("analysis_notes")
                )

                print(f"[PumpFunMonitor] New coin: {coin.get('name')} ({token_address[:8]}...) - Risk: {analysis['overall_risk_score']}")
            except Exception as e:
                print(f"[PumpFunMonitor] Failed to process coin {token_address}: {e}")

    def _fetch_pump_launches(self):
        """Fetch latest coin launches from Pump.fun"""
        # For MVP: Use mock data to ensure consistent demo data with market_cap and holders
        # TODO: When Pump.fun API is available and working, integrate real data
        return self._get_mock_coins()

    def _fetch_via_api(self):
        """Attempt to fetch from Pump.fun public API"""
        endpoints = [
            "https://api.pump.fun/coins?limit=50&sort=recent",
            "https://frontend-api.pump.fun/coins?limit=50&sort=recent",
        ]

        for url in endpoints:
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Accept": "application/json"
                })

                with urllib.request.urlopen(req, timeout=10) as response:
                    data = json.loads(response.read().decode('utf-8'))

                    coins = []
                    if isinstance(data, list):
                        for item in data:
                            coin = self._parse_pump_fun_coin(item)
                            if coin:
                                coins.append(coin)
                    elif isinstance(data, dict) and "coins" in data:
                        for item in data["coins"]:
                            coin = self._parse_pump_fun_coin(item)
                            if coin:
                                coins.append(coin)

                    if coins:
                        print(f"[PumpFunMonitor] Fetched {len(coins)} coins from Pump.fun API")
                        return coins
            except Exception as e:
                print(f"[PumpFunMonitor] API endpoint {url} failed: {e}")
                continue

        return None

    def _parse_pump_fun_coin(self, item):
        """Parse a coin from Pump.fun API response"""
        try:
            token_address = item.get("mint") or item.get("token_address")
            if not token_address:
                return None

            # Try to get holder count and market cap from API first, then on-chain
            holder_count = item.get("holder_count") or item.get("holders") or 0
            market_cap = item.get("market_cap") or 0

            # Only call RPC if we don't have these values from the API
            if not holder_count or not market_cap:
                try:
                    from services import solana_rpc
                    if not holder_count:
                        holders = solana_rpc.get_token_holders(token_address, limit=100)
                        holder_count = len(holders) if holders else 0

                    if not market_cap and holder_count > 0:
                        supply = solana_rpc.get_token_supply(token_address)
                        if supply > 0:
                            price_estimate = 0.00001
                            decimals = item.get("decimals", 6)
                            total_tokens = supply / (10 ** decimals)
                            market_cap = total_tokens * price_estimate
                except:
                    pass  # Use whatever values we have

            return {
                "token": token_address,
                "name": item.get("name", "Unknown"),
                "symbol": item.get("symbol", "???"),
                "description": item.get("description", ""),
                "creator": item.get("creator", ""),
                "url": f"https://pump.fun/coin/{token_address}",
                "market_cap": round(market_cap, 2) if market_cap else 0,
                "holders": holder_count
            }
        except Exception as e:
            print(f"[PumpFunMonitor] Error parsing coin: {e}")
            return None

    def _get_mock_coins(self):
        """Generate mock coins for demonstration"""
        # Deterministic token addresses so coins persist across monitor cycles
        # In production, this would fetch real data from Pump.fun API
        mock_data = [
            ("SafeMoon", "SAFE", "11111111111111111111111111111111", 125000.00, 2500),
            ("ElonFloki", "ELON", "22222222222222222222222222222222", 285000.00, 3200),
            ("MoonRocket", "MOON", "33333333333333333333333333333333", 450000.00, 4100),
            ("DoggySwap", "DOG", "44444444444444444444444444444444", 95000.00, 1800),
            ("CatMeme", "CAT", "55555555555555555555555555555555", 310000.00, 3500),
            ("PepeMax", "PEPE", "66666666666666666666666666666666", 205000.00, 2900),
        ]

        coins = []
        for name, prefix, token_addr, mc, holders in mock_data:
            coins.append({
                "token": token_addr,
                "name": name,
                "symbol": prefix,
                "description": f"A popular meme coin with strong community",
                "creator": "Pump" + "B" * 40,
                "url": f"https://pump.fun/coin/{prefix.lower()}",
                "market_cap": mc,
                "holders": holders
            })

        return coins


# Global instance
_monitor = None


def start_monitor(interval_seconds=15):
    """Initialize and start the global monitor"""
    global _monitor
    if _monitor is None:
        _monitor = PumpFunMonitor(update_interval_seconds=interval_seconds)
    _monitor.start()


def stop_monitor():
    """Stop the global monitor"""
    global _monitor
    if _monitor:
        _monitor.stop()
