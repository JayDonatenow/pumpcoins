"""Discover real newly-launched Solana tokens via RPC."""
import urllib.request
import urllib.error
import json
import time
from datetime import datetime, timedelta


class SolanaTokenDiscovery:
    """Find real tokens created on Solana blockchain"""

    def __init__(self, rpc_url="https://api.mainnet-beta.solana.com"):
        self.rpc_url = rpc_url
        self.token_program_id = "TokenkegQfeZyiNwAJsyFbPVwwQQfsSrxDcLS5LDLh"  # SPL Token Program
        self.last_signature = None

    def fetch_new_tokens(self, limit=20):
        """Fetch newly created tokens from recent blockchain transactions."""
        try:
            print("[SolanaTokenDiscovery] Fetching new tokens from Solana blockchain...")

            # Get recent transactions
            signatures = self._get_recent_signatures(limit=50)
            if not signatures:
                return []

            new_tokens = []
            for sig in signatures:
                try:
                    tx_data = self._get_transaction(sig['signature'])
                    if tx_data:
                        token = self._parse_token_mint(tx_data)
                        if token:
                            new_tokens.append(token)
                            if len(new_tokens) >= limit:
                                break
                except Exception as e:
                    continue

            print(f"[SolanaTokenDiscovery] Found {len(new_tokens)} new tokens")
            return new_tokens

        except Exception as e:
            print(f"[SolanaTokenDiscovery] Error: {e}")
            return []

    def _get_recent_signatures(self, limit=50):
        """Get recent transaction signatures."""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [
                    self.token_program_id,
                    {"limit": limit}
                ]
            }

            response = self._rpc_call(payload)
            if response and "result" in response:
                return response["result"]
            return []

        except Exception as e:
            print(f"[SolanaTokenDiscovery] Signature fetch error: {e}")
            return []

    def _get_transaction(self, signature):
        """Get full transaction data."""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [
                    signature,
                    {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}
                ]
            }

            response = self._rpc_call(payload)
            if response and "result" in response:
                return response["result"]
            return None

        except Exception as e:
            return None

    def _parse_token_mint(self, tx_data):
        """Extract token mint info from transaction."""
        try:
            if not tx_data or "transaction" not in tx_data:
                return None

            tx = tx_data["transaction"]
            instructions = tx.get("message", {}).get("instructions", [])

            for instr in instructions:
                # Look for token creation (InitializeMint instruction)
                if isinstance(instr, dict):
                    parsed = instr.get("parsed", {})
                    if parsed.get("type") == "initializeMint":
                        mint_addr = parsed.get("info", {}).get("mint")
                        decimals = parsed.get("info", {}).get("decimals")

                        if mint_addr:
                            return {
                                "token": mint_addr,
                                "name": f"Token {mint_addr[:8]}",
                                "symbol": mint_addr[:6].upper(),
                                "decimals": decimals,
                                "description": "Newly created token on Solana",
                                "creator": tx["transaction"].get("message", {}).get("accountKeys", [{}])[0],
                                "url": f"https://solscan.io/token/{mint_addr}",
                                "market_cap": 0,
                                "holders": 1,
                                "discovered_at": datetime.now().isoformat()
                            }

            return None

        except Exception as e:
            return None

    def _rpc_call(self, payload):
        """Make RPC call to Solana."""
        try:
            data = json.dumps(payload).encode()
            request = urllib.request.Request(
                self.rpc_url,
                data=data,
                headers={"Content-Type": "application/json"}
            )

            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode())

        except urllib.error.URLError as e:
            print(f"[SolanaTokenDiscovery] Network error: {e}")
            return None
        except Exception as e:
            print(f"[SolanaTokenDiscovery] RPC call error: {e}")
            return None


def fetch_solana_tokens(limit=20):
    """Public function to fetch real Solana tokens."""
    discovery = SolanaTokenDiscovery()
    return discovery.fetch_new_tokens(limit=limit)
