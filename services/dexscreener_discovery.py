"""Discover real Solana tokens from DexScreener API."""
import urllib.request
import urllib.error
import json
from datetime import datetime


class DexScreenerDiscovery:
    """Fetch token data from DexScreener - real token discovery."""

    def __init__(self):
        self.base_url = "https://api.dexscreener.com/latest/dex/tokens"
        self.timeout = 10

    def fetch_new_tokens(self, limit=20):
        """Fetch real trending/new tokens from DexScreener."""
        try:
            print("[DexScreener] Fetching tokens from DexScreener...")

            # Get trending tokens on Solana
            tokens = self._fetch_trending_tokens()

            if tokens and len(tokens) > 0:
                print(f"[DexScreener] ✅ Found {len(tokens)} real tokens from DexScreener")
                return tokens[:limit]
            else:
                print("[DexScreener] No tokens returned")
                return []

        except Exception as e:
            print(f"[DexScreener] Error: {e}")
            return []

    def _fetch_trending_tokens(self):
        """Fetch trending tokens from DexScreener."""
        try:
            # DexScreener trending tokens endpoint
            url = "https://api.dexscreener.com/latest/dex/trending"

            response = self._make_request(url)
            if response and "pairs" in response:
                tokens = self._parse_trending_pairs(response["pairs"])
                return tokens

            return []

        except Exception as e:
            print(f"[DexScreener] Trending fetch error: {e}")
            return []

    def _parse_trending_pairs(self, pairs):
        """Parse DexScreener trading pairs into token format."""
        tokens = []
        seen_tokens = set()

        for pair in pairs:
            try:
                # Filter for Solana only
                if pair.get("chainId") != "solana":
                    continue

                token_addr = pair.get("baseToken", {}).get("address")

                if not token_addr or token_addr in seen_tokens:
                    continue

                seen_tokens.add(token_addr)

                # Extract token info
                name = pair.get("baseToken", {}).get("name", "Token")
                symbol = pair.get("baseToken", {}).get("symbol", "???")

                # Get price and market data
                price_usd = pair.get("priceUsd", "0")
                try:
                    price = float(price_usd) if price_usd else 0
                except:
                    price = 0

                # Calculate rough market cap if we have price and liquidity
                liquidity = pair.get("liquidity", {}).get("usd", 0)
                market_cap = liquidity if liquidity > 0 else price * 1000000  # Estimate

                # Get volume as proxy for activity
                volume_24h = pair.get("volume", {}).get("usd", 0)

                tokens.append({
                    "token": token_addr,
                    "name": name,
                    "symbol": symbol,
                    "description": f"Trading on DexScreener - {pair.get('dexId', 'DEX')}",
                    "creator": "",
                    "url": f"https://dexscreener.com/solana/{pair.get('pairAddress')}",
                    "market_cap": float(market_cap) if market_cap else 0,
                    "holders": max(int(float(volume_24h) / price) if price > 0 else 50, 1),
                    "discovered_at": datetime.now().isoformat(),
                    "dex_id": pair.get("dexId"),
                    "pair_address": pair.get("pairAddress")
                })
            except Exception as e:
                continue

        return tokens

    def _make_request(self, url):
        """Make HTTP request to DexScreener API."""
        try:
            headers = {
                "User-Agent": "MemeCoinTrader/1.0",
                "Accept": "application/json"
            }

            request = urllib.request.Request(url, headers=headers)

            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = response.read().decode('utf-8')
                return json.loads(data)

        except urllib.error.HTTPError as e:
            print(f"[DexScreener] HTTP {e.code}")
            return None
        except urllib.error.URLError as e:
            print(f"[DexScreener] Network error: {e.reason}")
            return None
        except json.JSONDecodeError:
            print(f"[DexScreener] Invalid JSON")
            return None
        except Exception as e:
            print(f"[DexScreener] Request error: {e}")
            return None


def fetch_dexscreener_tokens(limit=20):
    """Public function to fetch real tokens from DexScreener."""
    discovery = DexScreenerDiscovery()
    return discovery.fetch_new_tokens(limit=limit)
