"""Solana RPC utilities for token analysis"""
import urllib.request
import urllib.error
import json
import time

RPC_URL = "https://api.mainnet-beta.solana.com"
REQUEST_TIMEOUT = 10


def _call_rpc(method, params):
    """Make a JSON-RPC call to Solana"""
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000) % 2**31,
            "method": method,
            "params": params
        }

        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            RPC_URL,
            data=data,
            headers={"Content-Type": "application/json"}
        )

        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
            result = json.loads(response.read().decode('utf-8'))

        if "error" in result:
            return None
        return result.get("result")
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, Exception):
        return None


def get_token_supply(token_address):
    """Get total token supply"""
    try:
        result = _call_rpc("getTokenSupply", [token_address])
        if result and "value" in result:
            return int(result["value"]["amount"])
        return 0
    except:
        return 0


def get_token_holders(token_address, limit=10):
    """Get top token holders"""
    try:
        result = _call_rpc("getTokenLargestAccounts", [token_address])
        if result and "value" in result:
            accounts = result["value"][:limit]
            return [
                {
                    "address": acc["address"],
                    "amount": int(acc["amount"]),
                    "decimals": acc["decimals"],
                    "uiAmount": acc.get("uiAmount", 0)
                }
                for acc in accounts
            ]
        return []
    except:
        return []


def get_token_metadata(token_address):
    """Get SPL token metadata"""
    try:
        result = _call_rpc("getAccountInfo", [token_address])
        if result and "value" in result:
            return {
                "lamports": result["value"]["lamports"],
                "owner": result["value"]["owner"],
                "executable": result["value"]["executable"]
            }
        return {}
    except:
        return {}


def get_account_info(account_address):
    """Get general account info"""
    try:
        result = _call_rpc("getAccountInfo", [account_address])
        if result and "value" in result:
            return dict(result["value"])
        return None
    except:
        return None


def simulate_transaction(transaction_message):
    """Simulate a transaction to check for errors (like honeypot)"""
    try:
        result = _call_rpc("simulateTransaction", [transaction_message])
        if result and "value" in result:
            return result["value"]
        return None
    except:
        return None


def get_balance(wallet_address):
    """Get wallet balance in lamports"""
    try:
        result = _call_rpc("getBalance", [wallet_address])
        if result:
            return result
        return 0
    except:
        return 0
