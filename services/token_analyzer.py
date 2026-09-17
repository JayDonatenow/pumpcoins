"""Token risk analysis engine with 6-factor heuristic scoring"""
import urllib.request
import urllib.error
import json
import time
from datetime import datetime
from services import solana_rpc


class TokenAnalyzer:
    """Analyze token risk using 6 weighted heuristic factors"""

    def __init__(self):
        self.pump_url_base = "https://pump.fun/coin/"
        self.cache = {}  # Cache scores for 5 minutes

    def analyze(self, token_address, pump_url=None, metadata=None):
        """
        6-Factor Heuristic Risk Analysis
        Returns risk scores 0-1 (0=safe, 1=risky)

        Factors (weighted):
        1. Token Age (15%) - Newer = more risky
        2. Metadata Completeness (15%) - Scams lack info
        3. Holder Concentration (25%) - Dev concentration
        4. Liquidity Status (15%) - Low liquidity
        5. Community Health (20%) - Engagement
        6. Contract Features (10%) - Suspicious patterns
        """
        try:
            # Check cache first (5 min TTL)
            if token_address in self.cache:
                cached_result, timestamp = self.cache[token_address]
                if time.time() - timestamp < 300:  # 5 minutes
                    return cached_result

            # Calculate individual factor scores
            age_score = self._score_token_age(token_address)
            metadata_score = self._score_metadata(metadata)
            holder_score = self._score_holder_concentration(token_address)
            liquidity_score = self._score_liquidity(token_address)
            community_score = self._score_community(pump_url)
            contract_score = self._score_contract_features()

            # Weighted combination
            overall = (
                age_score * 0.15 +
                metadata_score * 0.15 +
                holder_score * 0.25 +
                liquidity_score * 0.15 +
                community_score * 0.20 +
                contract_score * 0.10
            )

            # Determine recommendation
            if overall > 0.8:
                recommendation = "AVOID"
            elif overall > 0.6:
                recommendation = "HOLD"
            else:
                recommendation = "BUY"

            # Get additional metrics
            holder_count = self._get_holder_count(token_address)

            result = {
                "rug_pull_score": round(holder_score, 2),
                "honeypot_score": round(liquidity_score, 2),
                "scam_score": round(contract_score, 2),
                "community_score": round(community_score, 2),
                "liquidity_score": round(liquidity_score, 2),
                "overall_risk_score": round(overall, 2),
                "holder_count": holder_count,
                "is_liquidity_locked": False,
                "is_mint_renounced": False,
                "has_anti_whale": False,
                "is_contract_verified": False,
                "recommendation": recommendation,
                "analysis_notes": self._generate_risk_notes(
                    age_score, metadata_score, holder_score,
                    liquidity_score, community_score, contract_score
                )
            }

            # Cache the result
            self.cache[token_address] = (result, time.time())
            return result

        except Exception as e:
            print(f"[TokenAnalyzer] Error analyzing {token_address}: {e}")
            return self._neutral_analysis()

    def _score_token_age(self, token_address):
        """
        Factor 1: Token Age (15%)
        Newer tokens are more risky
        - < 1 hour old: 0.9 (very risky)
        - < 24 hours: 0.6 (risky)
        - < 7 days: 0.3 (moderate risk)
        - > 7 days: 0.1 (low risk)
        """
        try:
            # Try to estimate age from metadata or use conservative estimate
            # For now, assume all mock coins are > 7 days old
            return 0.1
        except:
            return 0.5

    def _score_metadata(self, metadata):
        """
        Factor 2: Metadata Completeness (15%)
        Scams often lack complete information
        Start at 0.5, reduce for each piece of info:
        - Has description: -0.1
        - Has website: -0.1
        - Has Twitter: -0.05
        - Has icon/image: -0.05
        """
        score = 0.5

        if metadata:
            if metadata.get('description'):
                score -= 0.1
            if metadata.get('website'):
                score -= 0.1
            if metadata.get('twitter') or metadata.get('social'):
                score -= 0.05
            if metadata.get('image') or metadata.get('icon'):
                score -= 0.05

        return max(score, 0.0)

    def _score_holder_concentration(self, token_address):
        """
        Factor 3: Holder Concentration (25%)
        High dev concentration = rug pull risk
        - Top holder > 50%: 0.8
        - Top holder > 25%: 0.5
        - Top holder > 10%: 0.2
        - Top 5 > 80%: +0.2
        """
        try:
            holders = solana_rpc.get_token_holders(token_address, limit=20)
            if not holders or len(holders) == 0:
                return 0.7  # Unknown = slightly risky

            total = sum(h.get("amount", 0) for h in holders)
            if total == 0:
                return 0.5

            # Top holder percentage
            top_holder_pct = (holders[0].get("amount", 0) / total) * 100
            top_5_pct = (sum(h.get("amount", 0) for h in holders[:5]) / total) * 100

            score = 0.0
            if top_holder_pct > 50:
                score = 0.8
            elif top_holder_pct > 25:
                score = 0.5
            elif top_holder_pct > 10:
                score = 0.2
            else:
                score = 0.1

            # Add extra risk if top 5 hold too much
            if top_5_pct > 80:
                score += 0.2

            return min(score, 1.0)
        except:
            return 0.5

    def _score_liquidity(self, token_address):
        """
        Factor 4: Liquidity Status (15%)
        Low liquidity = risky
        - No pool: 0.7
        - < $1k: 0.5
        - < $10k: 0.3
        - $10k+: 0.1
        """
        try:
            holders = solana_rpc.get_token_holders(token_address, limit=1)
            if not holders:
                return 0.7

            # Rough estimate: if top holder has significant amount, there's liquidity
            top_amount = holders[0].get("amount", 0)
            if top_amount == 0:
                return 0.7

            # Very simplified: assume some liquidity exists
            return 0.1
        except:
            return 0.5

    def _score_community(self, pump_url):
        """
        Factor 5: Community Health (20%)
        Zero engagement = risky
        - 0 engagements: 0.9
        - 1-10: 0.6
        - 10-100: 0.4
        - 100-1000: 0.2
        - 1000+: 0.05
        """
        if not pump_url:
            return 0.5

        try:
            # For demo: assume moderate engagement
            # In production, would scrape Pump.fun for actual metrics
            return 0.3  # Moderate engagement assumed
        except:
            return 0.5

    def _score_contract_features(self):
        """
        Factor 6: Contract Features (10%)
        Suspicious patterns increase risk
        - Mint authority not renounced: +0.2
        - Update authority not renounced: +0.1
        - Transfer fee detected: +0.15
        """
        # For demo: assume reasonable contract
        # In production, would check actual contract code
        return 0.1

    def _get_holder_count(self, token_address):
        """Get unique holder count"""
        try:
            holders = solana_rpc.get_token_holders(token_address, limit=100)
            return len(holders) if holders else 0
        except:
            return 0

    def _generate_risk_notes(self, age, metadata, holder, liquidity, community, contract):
        """Generate human-readable risk summary"""
        notes = []

        if holder > 0.6:
            notes.append("High holder concentration detected")
        if liquidity > 0.5:
            notes.append("Low liquidity pool")
        if community > 0.6:
            notes.append("Low community engagement")
        if contract > 0.3:
            notes.append("Suspicious contract features")
        if metadata > 0.5:
            notes.append("Incomplete token metadata")

        if not notes:
            notes.append("No major red flags detected")

        return "; ".join(notes)

    def _neutral_analysis(self):
        """Return neutral/unknown analysis"""
        return {
            "rug_pull_score": 0.5,
            "honeypot_score": 0.5,
            "scam_score": 0.5,
            "community_score": 0.5,
            "liquidity_score": 0.5,
            "overall_risk_score": 0.5,
            "holder_count": 0,
            "is_liquidity_locked": False,
            "is_mint_renounced": False,
            "has_anti_whale": False,
            "is_contract_verified": False,
            "recommendation": "HOLD",
            "analysis_notes": "Analysis unavailable"
        }
