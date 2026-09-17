# Meme Coin Trader - Advanced Features Implementation Plan

## Overview
Three interconnected features to build the complete trading experience:
1. **Phantom Wallet Integration** - Display wallet balance, link to external DEX trades
2. **Actual Risk Scoring** - Heuristic-based multi-factor risk detection
3. **Price Charts & History** - 7-day price tracking with frequent updates

---

## 1. Phantom Wallet Integration

### Frontend Changes (JavaScript)
- Add Phantom SDK detection and connection flow
- Show wallet balance in header (when connected)
- Display "Connect Wallet" button in unauthenticated state

### Backend Changes
- Track connected wallet address in session
- Generate Raydium trade links: `https://raydium.io/swap?inputMint=SOL&outputMint={TOKEN_ADDRESS}`
- Generate Jupiter trade links: `https://jup.ag/swap?inputMint=SOL&outputMint={TOKEN_ADDRESS}`
- Store wallet connections in `user_wallets` table for future use

### Database Schema Addition
```sql
CREATE TABLE user_wallets (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    wallet_address TEXT NOT NULL,
    connected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, wallet_address),
    FOREIGN KEY(user_id) REFERENCES users(id)
);
```

### UI Components
- Wallet connection button in navbar
- Wallet balance display (SOL)
- "Trade on Raydium" and "Trade on Jupiter" buttons on coin cards
- Wallet info modal showing connected address

---

## 2. Actual Risk Scoring (Heuristic-Based)

### Scoring Factors (Weighted)
1. **Token Age** (15%) - Newer = more risky
   - < 1 hour old: 0.9
   - < 24 hours: 0.6
   - < 7 days: 0.3
   - > 7 days: 0.1

2. **Metadata Completeness** (15%) - Scams lack info
   - Has description: -0.1
   - Has website: -0.1
   - Has Twitter: -0.05
   - Has icon/image: -0.05

3. **Holder Concentration** (25%) - Top holder % indicates rug risk
   - Top holder > 50%: 0.8
   - Top holder > 25%: 0.5
   - Top holder > 10%: 0.2
   - Top 5 holders > 80%: +0.2

4. **Liquidity Status** (15%) - Low liquidity = risky
   - No liquidity pool detected: 0.7
   - < $1k liquidity: 0.5
   - < $10k: 0.3
   - $10k+: 0.1

5. **Community Health** (20%) - Engagement signals
   - Zero holders: 0.9
   - < 10 holders: 0.7
   - 10-100 holders: 0.4
   - 100-1000: 0.2
   - 1000+: 0.05

6. **Contract Features** (10%) - Suspicious patterns
   - Mint authority not renounced: +0.2
   - Update authority not renounced: +0.1
   - Transfer fee detected: +0.15

### Implementation
- Add `get_heuristic_risk_score()` method to TokenAnalyzer
- Cache scores for 5 minutes (don't recalculate every request)
- Store in `coin_analysis.overall_risk_score`

---

## 3. Price Charts & History

### Database Schema Addition
```sql
CREATE TABLE coin_price_history (
    id INTEGER PRIMARY KEY,
    coin_id INTEGER NOT NULL,
    price REAL NOT NULL,
    market_cap REAL,
    holders INTEGER,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(coin_id) REFERENCES coins(id)
);

CREATE INDEX idx_price_history_coin_time 
ON coin_price_history(coin_id, recorded_at DESC);
```

### Data Collection
- Background task that runs every 5-10 seconds
- For each tracked coin, call `solana_rpc.get_token_supply()`
- Estimate price from DEX liquidity or use last known price
- Store price + market cap + holder count snapshot
- Prune data older than 7 days

### Frontend Components
- Add Chart.js for price visualization
- Display on coin detail page (`/coin/{address}`)
- Show: Price, Market Cap, Holder Count trends
- X-axis: Time (6h, 1d, 7d views)
- Y-axis: Price in USD or SOL

### API Endpoint
```
GET /api/coin/{address}/history?range=7d
Response: {
  "price_history": [
    {"timestamp": "2026-09-16T14:00:00Z", "price": 0.000015, "market_cap": 150000, "holders": 250},
    ...
  ]
}
```

---

## Implementation Sequence

### Phase 1: Price History (Foundation)
1. Add `coin_price_history` table to database
2. Add price collection background task
3. Add `/api/coin/{address}/history` endpoint
4. Add historical price display UI (dummy data first)

### Phase 2: Risk Scoring (Core Logic)
1. Update TokenAnalyzer with heuristic methods
2. Calculate scores for all coins
3. Update coins feed to show risk colors properly
4. Add risk breakdown modal (show which factors triggered)

### Phase 3: Phantom Wallet (Frontend UX)
1. Add Phantom SDK to HTML
2. Add wallet connection button and logic
3. Show wallet balance in header
4. Add DEX trade links to coin cards
5. Store wallet connection in database

### Phase 4: Integration & Polish
1. Update coin detail page with price chart
2. Add wallet info to user dashboard
3. Update watchlist to show price change
4. Add risk indicators to watchlist cards

---

## Technical Details

### Libraries Needed
- **Chart.js** (price charts) - via CDN
- **Phantom SDK** (wallet) - via CDN or npm
- No new backend dependencies needed

### Performance Considerations
- Cache risk scores for 5 minutes
- Prune price history older than 7 days daily
- Batch price updates every 10 seconds (not per coin)
- Lazy load charts on coin detail page

### Error Handling
- Graceful fallback if Phantom not installed
- Show "Unable to fetch price history" if data missing
- Continue app if wallet connection fails

---

## Testing Checklist

- [ ] Phantom wallet connects and shows balance
- [ ] DEX links work for Raydium and Jupiter
- [ ] Risk scores calculate correctly
- [ ] Price history stores and displays
- [ ] Charts render properly on all coin details
- [ ] Watchlist shows price changes
- [ ] Performance is acceptable with frequent updates
- [ ] Data prunes correctly after 7 days

---

## Estimated Timeline
- Phase 1: 2 hours
- Phase 2: 2 hours
- Phase 3: 1.5 hours
- Phase 4: 1 hour
- **Total: ~6.5 hours**
