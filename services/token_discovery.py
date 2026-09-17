"""Multi-source token discovery - tries free sources, falls back to paid Helius."""
import urllib.request
import urllib.error
import json
from datetime import datetime


class TokenDiscovery:
    """Try multiple sources: Magic Eden, Solscan, Jupiter, then Helius."""

    def __init__(self, helius_key=None):
        self.helius_key = helius_key or "YOUR_HELIUS_KEY_HERE"
        self.timeout = 8

    def fetch_new_tokens(self, limit=20):
        """Try free sources first, fall back to Helius if needed."""
        print("[TokenDiscovery] Attempting token discovery...")

        # Try free sources in order
        sources = [
            ("Magic Eden", self._try_magic_eden),
            ("Solscan", self._try_solscan),
            ("Jupiter (with headers)", self._try_jupiter_improved),
            ("Birdeye", self._try_birdeye),
        ]

        for source_name, source_func in sources:
            try:
                print(f"[TokenDiscovery] Trying {source_name}...")
                tokens = source_func(limit=limit)
                if tokens and len(tokens) > 5:
                    print(f"[TokenDiscovery] ✅ SUCCESS from {source_name}: {len(tokens)} tokens")
                    return tokens
            except Exception as e:
                print(f"[TokenDiscovery] {source_name} failed: {e}")
                continue

        # If all free sources failed, try Helius (requires API key)
        print("[TokenDiscovery] All free sources exhausted, trying Helius...")
        if self.helius_key != "YOUR_HELIUS_KEY_HERE":
            try:
                tokens = self._try_helius(limit=limit)
                if tokens and len(tokens) > 5:
                    print(f"[TokenDiscovery] ✅ SUCCESS from Helius: {len(tokens)} tokens")
                    return tokens
            except Exception as e:
                print(f"[TokenDiscovery] Helius failed: {e}")
        else:
            print("[TokenDiscovery] ⚠️  Helius API key not configured")

        print("[TokenDiscovery] ❌ No token sources available - using empty list")
        return []

    def _try_magic_eden(self, limit=20):
        """Try Magic Eden launchpad API."""
        try:
            url = "https://api.magiceden.io/v2/launchpad/collections"
            response = self._make_request(url, headers={"ME-API-KEY": "free"})
            if response:
                return self._parse_magic_eden(response, limit)
        except:
            pass
        return []

    def _try_solscan(self, limit=20):
        """Try Solscan API."""
        try:
            url = "https://api.solscan.io/api/token/list"
            response = self._make_request(url)
            if response and "data" in response:
                return self._parse_solscan(response["data"], limit)
        except:
            pass
        return []

    def _try_jupiter_improved(self, limit=20):
        """Try Jupiter with better headers."""
        try:
            url = "https://token.jup.ag/all"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
                "Accept": "application/json",
                "Referer": "https://jup.ag/",
                "Accept-Encoding": "gzip, deflate",
            }
            response = self._make_request(url, headers=headers)
            if response and isinstance(response, list):
                return self._parse_jupiter(response, limit)
        except:
            pass
        return []

    def _try_birdeye(self, limit=20):
        """Try Birdeye API - token discovery."""
        try:
            url = "https://public-api.birdeye.so/v1/public/tokenlist/solana"
            response = self._make_request(url)
            if response:
                return self._parse_birdeye(response, limit)
        except:
            pass
        return []

    def _try_helius(self, limit=20):
        """Try Helius RPC (requires API key)."""
        try:
            url = f"https://mainnet.helius-rpc.com/?api-key={self.helius_key}"
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": ["TokenkegQfeZyiNwAJsyFbPVwwQQfsSrxDcLS5LDLh", {"limit": limit}]
            }
            response = self._make_json_request(url, payload)
            if response and "result" in response:
                return self._parse_helius(response["result"], limit)
        except:
            pass
        return []

    def _parse_magic_eden(self, data, limit):
        """Parse Magic Eden response."""
        tokens = []
        for item in data[:limit]:
            try:
                tokens.append({
                    "token": item.get("address", ""),
                    "name": item.get("name", ""),
                    "symbol": item.get("symbol", ""),
                    "description": "Magic Eden launchpad",
                    "creator": "",
                    "url": f"https://magiceden.io/launchpad/{item.get('symbol')}",
                    "market_cap": float(item.get("floorPrice", 0)) * 1000 if item.get("floorPrice") else 0,
                    "holders": 50,
                    "discovered_at": datetime.now().isoformat()
                })
            except:
                continue
        return tokens

    def _parse_solscan(self, data, limit):
        """Parse Solscan response."""
        tokens = []
        for item in data[:limit]:
            try:
                tokens.append({
                    "token": item.get("address", ""),
                    "name": item.get("name", ""),
                    "symbol": item.get("symbol", ""),
                    "description": "Token from Solscan",
                    "creator": "",
                    "url": f"https://solscan.io/token/{item.get('address')}",
                    "market_cap": float(item.get("supply", 0)) * float(item.get("price", 0)) if item.get("price") else 0,
                    "holders": int(item.get("holder", 0)) if item.get("holder") else 50,
                    "discovered_at": datetime.now().isoformat()
                })
            except:
                continue
        return tokens

    def _parse_jupiter(self, data, limit):
        """Parse Jupiter token list."""
        tokens = []
        for item in data[:limit]:
            try:
                tokens.append({
                    "token": item.get("address", ""),
                    "name": item.get("name", ""),
                    "symbol": item.get("symbol", ""),
                    "description": "Jupiter token",
                    "creator": "",
                    "url": f"https://jup.ag/swap/{item.get('address')}",
                    "market_cap": 0,
                    "holders": 50,
                    "discovered_at": datetime.now().isoformat()
                })
            except:
                continue
        return tokens

    def _parse_birdeye(self, data, limit):
        """Parse Birdeye response."""
        tokens = []
        if "data" in data:
            for item in data["data"][:limit]:
                try:
                    tokens.append({
                        "token": item.get("address", ""),
                        "name": item.get("name", ""),
                        "symbol": item.get("symbol", ""),
                        "description": "Birdeye token",
                        "creator": "",
                        "url": f"https://birdeye.so/token/{item.get('address')}",
                        "market_cap": float(item.get("mc", 0)) if item.get("mc") else 0,
                        "holders": 50,
                        "discovered_at": datetime.now().isoformat()
                    })
                except:
                    continue
        return tokens

    def _parse_helius(self, data, limit):
        """Parse Helius response."""
        # Helius returns signatures, parse token creation from them
        return []

    def _make_request(self, url, headers=None):
        """Make HTTP request."""
        try:
            default_headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            }
            if headers:
                default_headers.update(headers)

            request = urllib.request.Request(url, headers=default_headers)
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except:
            return None

    def _make_json_request(self, url, payload):
        """Make JSON RPC request."""
        try:
            data = json.dumps(payload).encode('utf-8')
            request = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except:
            return None


def fetch_tokens(limit=20, helius_key=None):
    """Public function to discover tokens with fallback chain."""
    discovery = TokenDiscovery(helius_key=helius_key)
    return discovery.fetch_new_tokens(limit=limit)
