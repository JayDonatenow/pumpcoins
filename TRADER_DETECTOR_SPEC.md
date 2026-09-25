# Pump Coins — Meme Coin Trader/Detector (v1 Spec)

A real-time meme coin discovery and risk-detection platform for Solana. It surfaces new tokens as they launch, scores them for rug-pull and scam risk, and lets users track the ones worth watching — without placing trades on their behalf.

## What it does

- **Discovers** new meme coins in real time from Pump.fun, Jupiter, and DexScreener
- **Detects risk** using heuristics: holder concentration, liquidity depth, contract authorities, metadata completeness, and community signals
- **Tracks markets**: live price, market cap, and holder counts per coin
- **Watchlists & alerts**: follow coins and get notified on significant price or risk changes

## V1 scope

V1 is read-only: browse and track markets. No order execution, no wallet-held funds.

- [ ] Live coin feed with price / market cap / holder count
- [ ] Risk score per coin with a breakdown of contributing factors
- [ ] Coin detail page with price history chart
- [ ] Watchlist (add/remove coins, see them in one place)
- [ ] Search / filter the feed (by risk level, age, market cap)

Out of scope for v1: buy/sell execution, wallet fund custody, social/leaderboard features.

## Architecture

- `app.py` — Flask application and routes
- `models.py` — data models
- `db.py` — database access (SQLite)
- `services/`
  - `pump_monitor.py`, `token_discovery.py`, `solana_token_discovery.py`, `jupiter_discovery.py`, `dexscreener_discovery.py` — coin discovery sources
  - `token_analyzer.py`, `rugcheck_discovery.py` — risk scoring
  - `price_monitor.py`, `alert_monitor.py` — live price tracking and alerts
  - `solana_rpc.py` — on-chain data via Solana RPC
  - `twitter_monitor.py`, `fomo_scraper.py` — social/community signal sources

## Status

Early stage. Core discovery, risk-scoring, and monitoring services exist; this spec defines the v1 feature scope going forward. See `IMPLEMENTATION_PLAN.md` and `PHASE_4_PLAN.md` for prior planning notes on wallet integration, risk scoring, and price history — still relevant as reference for later phases.
