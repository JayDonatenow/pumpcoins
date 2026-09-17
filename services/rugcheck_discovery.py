"""Discover real newly-launched Solana tokens from Rugcheck API."""
import urllib.request
import urllib.error
import json
from datetime import datetime


class RugcheckDiscovery:
    """Fetch token data from Rugcheck - specialized in meme coin safety."""

    def __init__(self):
        self.base_url = "https://api.rugcheck.xyz/v1"
        self.timeout = 10

    def fetch_new_tokens(self, limit=20):
        """Fetch recently created tokens from Rugcheck."""
        try:
            print("[RugcheckDiscovery] Fetching new tokens from Rugcheck...")

            # Rugcheck's tokens endpoint for recent/trending tokens
            tokens = self._fetch_tokens(limit=limit)

            if tokens and len(tokens) > 0:
                print(f"[RugcheckDiscovery] Found {len(tokens)} real tokens from Rugcheck")
                return tokens
            else:
                print("[RugcheckDiscovery] No tokens returned")
                return []

        except Exception as e:
            print(f"[RugcheckDiscovery] Error: {e}")
            return []

    def _fetch_tokens(self, limit=20):
        """Fetch tokens from Rugcheck API."""
        try:
            # Try the tokens endpoint
            url = f"{self.base_url}/tokens/recent?limit={limit}"

            response = self._make_request(url)
            if response and isinstance(response, list):
                return self._parse_tokens(response)

            # Fallback: try trending tokens
            url = f"{self.base_url}/tokens/trending?limit={limit}"
            response = self._make_request(url)
            if response and isinstance(response, list):
                return self._parse_tokens(response)

            return []

        except Exception as e:
            print(f"[RugcheckDiscovery] Token fetch error: {e}")
            return []

    def _parse_tokens(self, token_list):
        """Parse Rugcheck token response into standard format."""
        parsed = []

        for token_data in token_list:
            try:
                if isinstance(token_data, dict):
                    token_addr = token_data.get("mint") or token_data.get("token") or token_data.get("address")

                    if not token_addr or len(token_addr) < 20:
                        continue

                    # Extract token info
                    name = token_data.get("name", f"Token {token_addr[:8]}")
                    symbol = token_data.get("symbol", token_addr[:6].upper())

                    # Get market data
                    market_cap = token_data.get("marketCap") or token_data.get("market_cap") or 0
                    holder_count = token_data.get("holders") or token_data.get("holder_count") or 1

                    # Get safety score from Rugcheck
                    risk_score = self._calculate_risk_score(token_data)

                    parsed.append({
                        "token": token_addr,
                        "name": name,
                        "symbol": symbol,
                        "description": token_data.get("description", "Real token from Solana blockchain"),
                        "creator": token_data.get("creator", ""),
                        "url": f"https://rugcheck.xyz/tokens/{token_addr}",
                        "market_cap": float(market_cap) if market_cap else 0,
                        "holders": int(holder_count) if holder_count else 1,
                        "discovered_at": datetime.now().isoformat(),
                        "rugcheck_score": risk_score
                    })
            except Exception as e:
                continue

        return parsed

    def _calculate_risk_score(self, token_data):
        """Extract or calculate risk score from Rugcheck data."""
        try:
            # Rugcheck provides various safety metrics
            risks = token_data.get("risks", [])

            if not risks:
                return 0.3  # Good score

            # Convert risks array to score (0-1, higher = riskier)
            risk_count = len(risks)
            if risk_count == 0:
                return 0.2
            elif risk_count <= 2:
                return 0.4
            elif risk_count <= 4:
                return 0.6
            else:
                return 0.8
        except:
            return 0.5

    def _make_request(self, url):
        """Make HTTP request to Rugcheck API."""
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
            print(f"[RugcheckDiscovery] HTTP {e.code}: {e.reason}")
            return None
        except urllib.error.URLError as e:
            print(f"[RugcheckDiscovery] Network error: {e.reason}")
            return None
        except json.JSONDecodeError:
            print(f"[RugcheckDiscovery] Invalid JSON response")
            return None
        except Exception as e:
            print(f"[RugcheckDiscovery] Request error: {e}")
            return None


def fetch_rugcheck_tokens(limit=20):
    """Public function to fetch real tokens from Rugcheck."""
    discovery = RugcheckDiscovery()
    return discovery.fetch_new_tokens(limit=limit)
