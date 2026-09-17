"""Discover real Solana tokens from Jupiter API."""
import urllib.request
import urllib.error
import json
from datetime import datetime


class JupiterDiscovery:
    """Fetch token data from Jupiter - leading Solana DEX aggregator."""

    def __init__(self):
        self.base_url = "https://token.jup.ag/all"
        self.timeout = 10

    def fetch_new_tokens(self, limit=20):
        """Fetch real tokens from Jupiter token list."""
        try:
            print("[Jupiter] Fetching REAL tokens from Jupiter...")

            tokens_data = self._fetch_all_tokens()

            if tokens_data and len(tokens_data) > 0:
                # Sort by volume/popularity and take trending ones
                sorted_tokens = sorted(
                    tokens_data,
                    key=lambda x: x.get("volume", 0),
                    reverse=True
                )
                print(f"[Jupiter] ✅ Found {len(sorted_tokens)} real tokens from Jupiter")
                return sorted_tokens[:limit]
            else:
                print("[Jupiter] No tokens returned")
                return []

        except Exception as e:
            print(f"[Jupiter] Error: {e}")
            return []

    def _fetch_all_tokens(self):
        """Fetch all tokens from Jupiter."""
        try:
            response = self._make_request(self.base_url)
            if response and isinstance(response, list):
                return self._parse_tokens(response)

            return []

        except Exception as e:
            print(f"[Jupiter] Token fetch error: {e}")
            return []

    def _parse_tokens(self, tokens_list):
        """Parse Jupiter token list into standard format."""
        parsed = []

        for token_data in tokens_list:
            try:
                if isinstance(token_data, dict):
                    token_addr = token_data.get("address")

                    if not token_addr or len(token_addr) < 40:
                        continue

                    name = token_data.get("name", f"Token {token_addr[:8]}")
                    symbol = token_data.get("symbol", "???")
                    decimals = token_data.get("decimals", 6)

                    # Estimate market data (Jupiter doesn't provide market cap directly)
                    volume = float(token_data.get("volumeUSD", 0)) if token_data.get("volumeUSD") else 0

                    # Use volume as market cap proxy, or estimate based on activity
                    market_cap = volume * 0.5 if volume > 0 else 0

                    parsed.append({
                        "token": token_addr,
                        "name": name,
                        "symbol": symbol,
                        "description": "Real token from Jupiter - Solana's leading DEX",
                        "creator": "",
                        "url": f"https://jup.ag/swap/{token_addr}",
                        "market_cap": float(market_cap),
                        "holders": max(int(volume / 100) if volume > 0 else 50, 1),
                        "discovered_at": datetime.now().isoformat(),
                        "volume_usd": volume,
                        "decimals": decimals
                    })
            except Exception as e:
                continue

        return parsed

    def _make_request(self, url):
        """Make HTTP request to Jupiter API."""
        try:
            headers = {
                "User-Agent": "MemeCoinTrader/1.0 (+https://github.com)",
                "Accept": "application/json",
                "Cache-Control": "max-age=3600"
            }

            request = urllib.request.Request(url, headers=headers)

            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = response.read().decode('utf-8')
                return json.loads(data)

        except urllib.error.HTTPError as e:
            print(f"[Jupiter] HTTP {e.code}")
            return None
        except urllib.error.URLError as e:
            print(f"[Jupiter] Network error: {e.reason}")
            return None
        except json.JSONDecodeError:
            print(f"[Jupiter] Invalid JSON")
            return None
        except Exception as e:
            print(f"[Jupiter] Request error: {e}")
            return None


def fetch_jupiter_tokens(limit=20):
    """Public function to fetch real tokens from Jupiter."""
    discovery = JupiterDiscovery()
    return discovery.fetch_new_tokens(limit=limit)
