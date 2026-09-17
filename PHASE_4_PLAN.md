# Phase 4: Real Pump.fun API Integration - Early Coin Discovery

## Current State
- Using 6 hardcoded mock coins
- No real-time monitoring of new launches
- No way to catch coins in early stages

## Goal
Find **new meme coins within minutes of launch** before they trend, enabling early entry for traders.

---

## What Needs to Be Done

### 1. **Real Pump.fun API Integration** (High Priority)
Replace mock data with actual Pump.fun data:

**Option A: Pump.fun Public API** (Easiest)
```
GET https://api.pump.fun/coins?limit=50&sort=recent&minMarketCap=0
```
- Returns newest coin launches
- Includes: name, symbol, market cap, holders, description, creator, image
- Rate limits: ~60 req/min (check docs)

**Option B: Blockchain Monitoring** (Most Accurate)
- Monitor Solana blockchain for new SPL token creation
- Detect Pump.fun token launches from blockchain events
- Requires Solana RPC: `getProgramAccounts()` for token program
- More reliable but more complex

**Recommendation: Start with Option A (Pump.fun API)**
- Faster to implement (1-2 hours)
- Reliable for Pump.fun coins specifically
- Falls back to mock if API fails

---

### 2. **Real-Time Monitoring Service**
Update `services/pump_monitor.py`:

Current: Fetches mock coins every 15 seconds
Needed: 
- Fetch from real Pump.fun API (or blockchain)
- **Key: Detect coins by `discovered_at` timestamp**
- If `discovered_at < 1 hour`, mark as "🔥 NEW"
- If `discovered_at < 24 hours`, mark as "⏰ RECENT"

```python
# New fields to track
NEW_THRESHOLD = 1 * 60 * 60  # 1 hour = brand new
RECENT_THRESHOLD = 24 * 60 * 60  # 24 hours = recent

def get_coin_freshness(discovered_at):
    age_seconds = (datetime.now() - discovered_at).total_seconds()
    if age_seconds < NEW_THRESHOLD:
        return "NEW", "🔥"
    elif age_seconds < RECENT_THRESHOLD:
        return "RECENT", "⏰"
    return "ESTABLISHED", ""
```

---

### 3. **Discovery Feed UI**
Add new sections to coins feed:

```
┌─────────────────────────────────────────────┐
│ 🔥 BRAND NEW (< 1 hour old)                 │
│ ┌─────────┬─────────┬─────────┐             │
│ │ Coin A  │ Coin B  │ Coin C  │  ← Fresh   │
│ │ 5 min   │ 12 min  │ 48 min  │            │
│ └─────────┴─────────┴─────────┘             │
├─────────────────────────────────────────────┤
│ ⏰ RECENT (< 24 hours old)                   │
│ ┌─────────┬─────────┬─────────┐             │
│ │ Coin D  │ Coin E  │ Coin F  │  ← 6h old  │
│ │         │         │         │            │
│ └─────────┴─────────┴─────────┘             │
├─────────────────────────────────────────────┤
│ ✓ ESTABLISHED (> 24 hours old)              │
│ [All discovered coins sorted by age]        │
└─────────────────────────────────────────────┘
```

---

### 4. **Filtering by Freshness**
Add filter to coins feed:

```html
<select>
  <option value="all">All Coins</option>
  <option value="new">🔥 Brand New (< 1h)</option>
  <option value="recent">⏰ Recent (< 24h)</option>
  <option value="established">✓ Established</option>
</select>
```

Route: `/coins?filter=new` → Shows only coins < 1 hour old

---

### 5. **Early Detection Alerts** (Optional but Powerful)
Add real-time notifications:

```
Browser Notifications:
"🔥 NEW: SolanaDoge ($45k market cap) just launched! View →"

Sound Alert: Play chime when new coin appears
Desktop Badge: Show "5 new coins" on tab

Stored in: `coin_launches` table with timestamps
```

---

### 6. **Key Metrics for Early Entry**
Display on every coin card:

```
TIME SINCE LAUNCH: 12 minutes ago (age badge)
INITIAL MARKET CAP: $8,500
CURRENT MARKET CAP: $45,000 (↑ 5.3x growth!)
INITIAL HOLDERS: 18
CURRENT HOLDERS: 247 (↑ growing activity)
```

This shows traders:
- How old the coin is
- How much it's already grown
- Momentum (holder growth rate)

---

## Implementation Order

### Phase 4a: API Integration (2-3 hours)
1. Get Pump.fun API endpoint working
2. Replace `_fetch_pump_launches()` to use real API
3. Add fallback to mock data if API fails
4. Test with real coins

### Phase 4b: UI Updates (1-2 hours)
1. Add coin freshness tracking (age badges)
2. Add filter dropdown for "New/Recent/Established"
3. Display "time since launch" on coins
4. Add visual indicators (🔥 for brand new)

### Phase 4c: Alerts (Optional, 1-2 hours)
1. Browser notifications when new coin appears
2. Sound alert option
3. Tab badge counter
4. Notification history

### Phase 4d: Momentum Tracking (1 hour)
1. Calculate market cap growth rate
2. Calculate holder growth rate
3. Show on coin cards

---

## Code Changes Needed

### File: `services/pump_monitor.py`
```python
def _fetch_pump_launches(self):
    # Change from mock to real API
    try:
        return self._fetch_via_pump_api()
    except:
        print("[PumpFunMonitor] API failed, falling back to mock")
        return self._get_mock_coins()

def _fetch_via_pump_api(self):
    url = "https://api.pump.fun/coins?limit=50&sort=recent"
    response = requests.get(url, timeout=10)
    coins = response.json()
    return [self._parse_coin(c) for c in coins]
```

### File: `app.py`
```python
# Update coins_feed() to show freshness
def get_coin_age_badge(coin):
    if coin['discovered_at'] < 1 hour:
        return "🔥 BRAND NEW"
    elif coin['discovered_at'] < 24 hours:
        return "⏰ RECENT"
    return ""

# Add filter parameter
if query.get('filter') == 'new':
    coins = [c for c in coins if c['age'] < 1 hour]
```

---

## Dependencies to Add

Currently: **zero external dependencies** (only stdlib)

Option 1: Keep using stdlib `urllib`
```python
import urllib.request
response = urllib.request.urlopen(url)
data = json.loads(response.read())
```

Option 2: Use `requests` library (cleaner but adds dependency)
```python
import requests
response = requests.get(url)
data = response.json()
```

**Recommendation: Stick with urllib** (maintain zero dependencies)

---

## API Rate Limiting

Pump.fun API typical limits: **60 requests/minute**

Current: Polling every 15 seconds = 4 req/min ✓ Safe
If adding blockchain monitoring: Could be 100+ req/min → Need caching

Solution: Cache coin data for 30-60 seconds between polls

---

## Testing Strategy

1. **Test with real Pump.fun API** (verify coin data)
2. **Test age calculation** (ensure timestamps are correct)
3. **Test filtering** (verify fresh coins appear in "New" tab)
4. **Test fallback** (mock coins if API unavailable)
5. **Monitor for 24 hours** (catch real new launches)

---

## Success Metrics

✓ Coins appear in "New" section within 5-10 minutes of launch
✓ Market cap and holders updating in real-time
✓ Risk scores calculated immediately on new coins
✓ Users can filter by freshness
✓ No crashes from API changes
✓ Graceful fallback if API goes down

---

## Next Steps

1. **Get Pump.fun API Documentation** → Check if free/public
2. **Update pump_monitor.py** → Implement real API fetch
3. **Update UI** → Add freshness badges and filters
4. **Test with real coins** → Verify early detection works
5. **Monitor** → Track how fast coins appear vs manual check

---

## Timeline: ~4-6 hours total
- Phase 4a (API): 2-3 hours
- Phase 4b (UI): 1-2 hours  
- Phase 4c (Alerts): 1-2 hours (optional)
- Testing: 1 hour

**Estimated Ship Date: Today (if you want to start now!)**
