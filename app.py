#!/usr/bin/env python3
"""Meme Coin Trader - Standalone trading platform for discovering and analyzing Solana meme coins."""

import json
import re
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from datetime import datetime
from hashlib import sha256

import db
import models
from services.pump_monitor import start_monitor, stop_monitor, refresh_coins
from services.price_monitor import start_monitor as start_price_monitor, stop_monitor as stop_price_monitor
from services.alert_monitor import start_monitor as start_alert_monitor, stop_monitor as stop_alert_monitor
from services.twitter_monitor import start_monitor as start_twitter_monitor, stop_monitor as stop_twitter_monitor, get_twitter_data
from services.token_analyzer import TokenAnalyzer

HOST, PORT = '127.0.0.1', 8001

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)

        # Route: GET /
        if path == '/' or path == '':
            self.render("Pump Trader", self.home_page())
            return

        # Route: GET /coins
        if path == '/coins':
            coins = models.get_latest_coins(limit=50)
            analyses = {}
            for coin in coins:
                analysis = models.get_coin_analysis(coin['id'])
                analyses[coin['id']] = analysis

            user = self.get_user()
            self.render("Pump Trader - Coin Discoveries", self.coins_feed(coins, analyses, user, query))
            return

        # Route: GET /coin/{address}
        match = re.match(r'/coin/([a-zA-Z0-9]+)', path)
        if match:
            address = match.group(1)
            coin = models.get_coin_by_address(address)
            if coin:
                analysis = models.get_coin_analysis(coin['id'])
                self.render(f"{coin.get('name', 'Coin')} Details", self.coin_detail(coin, analysis))
            else:
                self.render("Not Found", "<p>Coin not found</p>")
            return

        # Route: GET /trade/{address}
        match = re.match(r'/trade/([a-zA-Z0-9]+)', path)
        if match:
            address = match.group(1)
            user = self.get_user()
            if not user:
                self.redirect('/login')
                return

            coin = models.get_coin_by_address(address)
            if coin:
                analysis = models.get_coin_analysis(coin['id'])
                self.render(f"Trade {coin.get('symbol', 'Coin')}", self.trade_page(coin, analysis))
            else:
                self.render("Not Found", "<p>Coin not found</p>")
            return

        # Route: GET /dashboard
        if path == '/dashboard':
            user = self.get_user()
            if not user:
                self.redirect('/login')
                return

            watchlist = models.get_user_watchlist(user['id'])
            trades = models.get_user_trades(user['id'])

            analyses = {}
            for coin in watchlist:
                analysis = models.get_coin_analysis(coin['id'])
                analyses[coin['id']] = analysis

            self.render("Dashboard", self.dashboard_page(user, watchlist, trades, analyses))
            return

        # Route: GET /me/watchlist
        if path == '/me/watchlist':
            user = self.get_user()
            if not user:
                self.redirect('/login')
                return

            coins = models.get_user_watchlist(user['id'])
            analyses = {}
            for coin in coins:
                analysis = models.get_coin_analysis(coin['id'])
                analyses[coin['id']] = analysis

            self.render("My Watchlist", self.watchlist_page(coins, analyses, user))
            return

        # Route: GET /logout
        if path == '/logout':
            self.set_cookie('session', '', max_age=0)
            self.redirect('/')
            return

        # Route: GET /login
        if path == '/login':
            self.render("Log In", self.login_page())
            return

        # Route: GET /signup
        if path == '/signup':
            self.render("Sign Up", self.signup_page())
            return

        # Route: GET /api/coins
        if path == '/api/coins':
            coins = models.get_latest_coins(limit=50)
            analyses = {}
            for coin in coins:
                analysis = models.get_coin_analysis(coin['id'])
                analyses[coin['id']] = analysis

            data = {
                "coins": [
                    {**coin, "analysis": analyses.get(coin['id'], {})}
                    for coin in coins
                ]
            }
            self.json_response(data)
            return

        # Route: GET /api/coin/{address}/history
        match = re.match(r'/api/coin/([a-zA-Z0-9]+)/history', path)
        if match:
            address = match.group(1)
            coin = models.get_coin_by_address(address)
            if coin:
                history = models.get_price_history(coin['id'], hours=168)
                self.json_response({
                    "coin": {
                        "id": coin['id'],
                        "address": coin['token_address'],
                        "name": coin['name'],
                        "symbol": coin['symbol']
                    },
                    "price_history": [dict(h) for h in history]
                })
            else:
                self.json_response({"error": "Coin not found"})
            return

        # Route: GET /api/refresh-coins
        if path == '/api/refresh-coins':
            try:
                refresh_coins()
                coins = models.get_latest_coins(limit=20)
                analyses = {}
                for coin in coins:
                    analysis = models.get_coin_analysis(coin['id'])
                    analyses[coin['id']] = analysis

                data = {
                    "success": True,
                    "coins": [
                        {**coin, "analysis": analyses.get(coin['id'], {})}
                        for coin in coins
                    ]
                }
                self.json_response(data)
            except Exception as e:
                self.json_response({"success": False, "error": str(e)})
            return

        self.not_found()

    def do_POST(self):
        path = urlparse(self.path).path
        content_len = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_len).decode()
        data = parse_qs(body)

        # Route: POST /login
        if path == '/login':
            email = data.get('email', [''])[0]
            password = data.get('password', [''])[0]

            user = models.get_user_by_email(email)
            if user and models.verify_password(password, user['password_hash']):
                token, csrf = models.create_session(user['id'])
                self.redirect('/dashboard', 'session', token)
            else:
                self.render("Log In", self.login_page(error="Invalid email or password"))
            return

        # Route: POST /signup
        if path == '/signup':
            email = data.get('email', [''])[0]
            password = data.get('password', [''])[0]
            name = data.get('name', [''])[0]

            if models.create_user(email, password, name):
                user = models.get_user_by_email(email)
                token, csrf = models.create_session(user['id'])
                self.redirect('/dashboard', 'session', token)
            else:
                self.render("Sign Up", self.signup_page(error="Email already exists"))
            return

        # Route: POST /watchlist/add/{address}
        match = re.match(r'/watchlist/add/([a-zA-Z0-9]+)', path)
        if match:
            user = self.get_user()
            if user:
                address = match.group(1)
                coin = models.get_coin_by_address(address)
                if coin:
                    models.add_to_watchlist(user['id'], coin['id'])
            self.json_response({"ok": True})
            return

        # Route: POST /watchlist/remove/{coin_id}
        match = re.match(r'/watchlist/remove/(\d+)', path)
        if match:
            user = self.get_user()
            if user:
                coin_id = match.group(1)
                conn = db.connect()
                conn.execute("DELETE FROM user_watchlist WHERE user_id=? AND coin_id=?",
                           (user['id'], coin_id))
                conn.commit()
                conn.close()
            self.json_response({"ok": True})
            return

        # Route: POST /api/trade
        if path == '/api/trade':
            user = self.get_user()
            if user:
                coin_id = data.get('coin_id', [''])[0]
                action = data.get('action', [''])[0]
                amount = data.get('amount_sol', [''])[0]
                models.log_trade(user['id'], coin_id, action, float(amount) if amount else 0)
            self.json_response({"ok": True})
            return

        # Route: POST /api/wallet/connect
        if path == '/api/wallet/connect':
            user = self.get_user()
            if user:
                try:
                    payload = json.loads(body)
                    wallet_address = payload.get('wallet_address')
                    if wallet_address:
                        models.add_wallet(user['id'], wallet_address)
                        self.json_response({"ok": True})
                    else:
                        self.json_response({"ok": False, "error": "Missing wallet_address"})
                except:
                    self.json_response({"ok": False, "error": "Invalid request"})
            else:
                self.json_response({"ok": False, "error": "Not authenticated"})
            return

        self.not_found()

    def home_page(self):
        coins = models.get_latest_coins(limit=6)
        analyses = {}
        for coin in coins:
            analysis = models.get_coin_analysis(coin['id'])
            analyses[coin['id']] = analysis

        coin_cards = ''.join([
            f"""<div class="coin-card">
                <h3>{coin['name']}</h3>
                <p class="symbol">{coin.get('symbol', '?')}</p>
                <p class="price">${coin.get('market_cap', 0):,.2f} market cap</p>
                <p class="holders">{coin.get('holder_count', 0)} holders</p>
                <a href="/coins" class="btn">Browse All</a>
            </div>"""
            for coin in coins
        ])

        user = self.get_user()
        logged_in = f'<a href="/dashboard" class="btn btn-primary">Dashboard</a>' if user else '<a href="/login" class="btn btn-primary">Log In</a>'

        return f"""
        <div class="home">
            <h1>🚀 Pump Trader</h1>
            <p class="subtitle">Discover and analyze Solana meme coins with real-time risk scoring</p>

            <div class="featured-coins">
                {coin_cards or '<p>No coins discovered yet. Check back soon!</p>'}
            </div>

            <div class="cta">
                <a href="/coins" class="btn">Browse All Coins</a>
                {logged_in}
            </div>
        </div>
        """

    def coins_feed(self, coins, analyses, user, query):
        # Get sort and filter parameters
        sort_by = query.get('sort', ['newest'])[0]
        search = query.get('search', [''])[0].lower()
        freshness_filter = query.get('freshness', ['all'])[0]
        momentum_filter = query.get('momentum', ['all'])[0]

        # Filter coins by search
        filtered_coins = [c for c in coins if search in c['name'].lower() or search in c.get('symbol', '').lower()]

        # Filter coins by freshness
        if freshness_filter != 'all':
            freshness_coins = []
            for c in filtered_coins:
                status, _, _ = self.coin_freshness(c)
                if freshness_filter == 'new' and status == 'NEW':
                    freshness_coins.append(c)
                elif freshness_filter == 'recent' and status == 'RECENT':
                    freshness_coins.append(c)
                elif freshness_filter == 'established' and status == 'ESTABLISHED':
                    freshness_coins.append(c)
            filtered_coins = freshness_coins

        # Sort coins
        if sort_by == 'market_cap':
            filtered_coins.sort(key=lambda x: x.get('market_cap', 0), reverse=True)
        elif sort_by == 'holders':
            filtered_coins.sort(key=lambda x: x.get('holder_count', 0), reverse=True)
        elif sort_by == 'risk_high':
            filtered_coins.sort(key=lambda x: analyses.get(x['id'], {}).get('overall_risk_score', 0.5), reverse=True)
        elif sort_by == 'risk_low':
            filtered_coins.sort(key=lambda x: analyses.get(x['id'], {}).get('overall_risk_score', 0.5))
        elif sort_by == 'trending':
            # Sort by holder count (proxy for trending)
            filtered_coins.sort(key=lambda x: x.get('holder_count', 0), reverse=True)

        watchlist_ids = set()
        if user:
            wl = models.get_user_watchlist(user['id'])
            watchlist_ids = {c['id'] for c in wl}

        cards = []
        for c in filtered_coins:
            watchlist_btn = ""
            if user:
                if c['id'] in watchlist_ids:
                    watchlist_btn = f'<button class="btn btn-watchlist" onclick="removeWatchlist({c["id"]})">Remove ❤️</button>'
                else:
                    watchlist_btn = f'<button class="btn btn-watchlist" onclick="addWatchlist(\'{c["token_address"]}\')">Add to Watchlist ♡</button>'

            risk_score = analyses.get(c['id'], {}).get('overall_risk_score', 0.5)
            score_display = f"{risk_score:.2f}" if risk_score is not None else "?"
            safety_percent = int((1 - risk_score) * 100) if risk_score is not None else 50

            freshness_status, freshness_emoji, freshness_time = self.coin_freshness(c)
            freshness_badge = f'<span class="freshness-badge freshness-{freshness_status.lower()}">{freshness_emoji} {freshness_time}</span>' if freshness_emoji else ""

            # Safety color based on percentage
            if safety_percent >= 70:
                safety_color = "#10b981"  # Green
            elif safety_percent >= 50:
                safety_color = "#f59e0b"  # Yellow
            else:
                safety_color = "#ef4444"  # Red

            # Get Twitter data
            twitter_data = get_twitter_data(c['id'])
            if twitter_data and (twitter_data.get('tweets', 0) > 0 or twitter_data.get('likes', 0) > 0):
                twitter_section = f"""
                <div class="twitter-data">
                    <div class="twitter-label">🐦 Twitter Activity</div>
                    <div class="twitter-stats">
                        <span class="twitter-stat">💬 {twitter_data.get('tweets', 0)}</span>
                        <span class="twitter-stat">❤️ {twitter_data.get('likes', 0):,}</span>
                        <span class="twitter-stat">🔄 {twitter_data.get('retweets', 0):,}</span>
                        <span class="twitter-stat">💬 {twitter_data.get('replies', 0):,}</span>
                    </div>
                </div>
                """
            else:
                twitter_section = """
                <div class="twitter-data" style="opacity: 0.6;">
                    <div class="twitter-label">🐦 Twitter Activity</div>
                    <div class="twitter-stats" style="color: #999; font-size: 0.85rem;">
                        <span>Monitoring tweets...</span>
                    </div>
                </div>
                """

            card = f"""<div class="coin-card risk-{self.risk_level(risk_score)}">
                <div class="coin-header">
                    <div>
                        <h3>{c['name']}</h3>
                        <p class="symbol">{c.get('symbol', '?')}{' ' + freshness_badge if freshness_badge else ''}</p>
                    </div>
                    <div class="safety-box" style="background: {safety_color};">
                        <div class="safety-percent">{safety_percent}%</div>
                        <div class="safety-label">Safe</div>
                    </div>
                </div>
                <div class="metrics">
                    <div class="metric">
                        <span>Market Cap</span>
                        <span class="value">${c.get('market_cap', 0):,.2f}</span>
                    </div>
                    <div class="metric">
                        <span>Holders</span>
                        <span class="value">{c.get('holder_count', 0):,}</span>
                    </div>
                </div>
                {twitter_section}
                <div class="actions">
                    <a href="/coin/{c['token_address']}" class="btn">Details</a>
                    <a href="/trade/{c['token_address']}" class="btn btn-primary">Trade</a>
                    <button class="btn btn-copy" onclick="copyToClipboard('{c['token_address']}', this)">📋 Copy Address</button>
                    {watchlist_btn}
                </div>
            </div>"""
            cards.append(card)

        cards = ''.join(cards)

        sort_newest = 'selected' if sort_by == 'newest' else ''
        sort_mcap = 'selected' if sort_by == 'market_cap' else ''
        sort_holders = 'selected' if sort_by == 'holders' else ''
        sort_trending = 'selected' if sort_by == 'trending' else ''
        sort_low_risk = 'selected' if sort_by == 'risk_low' else ''
        sort_high_risk = 'selected' if sort_by == 'risk_high' else ''

        fresh_all = 'selected' if freshness_filter == 'all' else ''
        fresh_new = 'selected' if freshness_filter == 'new' else ''
        fresh_recent = 'selected' if freshness_filter == 'recent' else ''
        fresh_established = 'selected' if freshness_filter == 'established' else ''

        # Get Twitter-active coins for display at top
        twitter_section_html = ""
        twitter_active_coins = []
        for c in coins[:20]:
            twitter_data = get_twitter_data(c['id'])
            if twitter_data and (twitter_data.get('tweets', 0) > 0 or twitter_data.get('likes', 0) > 0):
                twitter_active_coins.append((c, twitter_data))

        if twitter_active_coins:
            twitter_cards = []
            for c, twitter_data in twitter_active_coins[:5]:
                twitter_cards.append(f"""<div class="coin-card" style="border-top: 3px solid #1da1f2;">
                    <div class="coin-header">
                        <div><h3>{c['name']}</h3><p class="symbol">{c.get('symbol', '?')}</p></div>
                    </div>
                    <div style="background: #0a1929; border-left: 3px solid #1da1f2; padding: 1rem; border-radius: 4px; margin: 0.75rem 0;">
                        <div style="color: #1da1f2; font-size: 0.85rem; font-weight: bold; margin-bottom: 0.5rem;">🐦 Twitter Activity</div>
                        <div style="display: flex; gap: 1rem; font-size: 0.9rem;">
                            <span>💬 {twitter_data.get('tweets', 0)} tweets</span>
                            <span>❤️ {twitter_data.get('likes', 0):,} likes</span>
                            <span>🔄 {twitter_data.get('retweets', 0):,} retweets</span>
                        </div>
                    </div>
                    <div class="actions">
                        <a href="/coin/{c['token_address']}" class="btn">Details</a>
                        <a href="/trade/{c['token_address']}" class="btn btn-primary">Trade</a>
                    </div>
                </div>""")

            twitter_section_html = f"""
            <div class="trending-section" style="border-top: 3px solid #1da1f2; background: rgba(29, 161, 242, 0.05); padding: 2rem; border-radius: 8px; margin-bottom: 2rem;">
                <h2>🐦 Twitter Trends (Live Mentions)</h2>
                <div class="coins-grid">
                    {''.join(twitter_cards)}
                </div>
            </div>
            """
        else:
            twitter_section_html = """
            <div class="trending-section" style="border-top: 3px solid #1da1f2; background: rgba(29, 161, 242, 0.05); padding: 2rem; border-radius: 8px; margin-bottom: 2rem; text-align: center; color: #999;">
                <h2>🐦 Twitter Trends</h2>
                <p>Monitoring tweets... Tweets will appear here once coins are mentioned on Twitter.</p>
                <p style="font-size: 0.85rem; margin-top: 1rem; color: #666;">Make sure TWITTER_BEARER_TOKEN is set to enable tracking</p>
            </div>
            """

        # Get trending coins for display at top
        trending_coins = models.get_trending_coins(limit=5)
        trending_section = ""
        if trending_coins:
            trending_html = []
            for tc in trending_coins:
                tc_analysis = analyses.get(tc['id'], {})
                risk_score = tc_analysis.get('overall_risk_score', 0.5)
                safety_percent = int((1 - risk_score) * 100)
                if safety_percent >= 70:
                    safety_color = '#10b981'
                elif safety_percent >= 50:
                    safety_color = '#f59e0b'
                else:
                    safety_color = '#ef4444'

                holder_growth = tc.get('holder_growth', 0)
                growth_badge = f"<span style='background: #10b981; padding: 0.25rem 0.75rem; border-radius: 20px; font-size: 0.8rem; font-weight: bold;'>📈 +{holder_growth} holders</span>"

                trending_html.append(f"""<div class="coin-card risk-{self.risk_level(risk_score)}" style="border-top: 3px solid #10b981;">
                    <div class="coin-header">
                        <div><h3>{tc['name']}</h3><p class="symbol">{tc.get('symbol', '?')} {growth_badge}</p></div>
                        <div class="safety-box" style="background: {safety_color};">
                            <div class="safety-percent">{safety_percent}%</div>
                            <div class="safety-label">Safe</div>
                        </div>
                    </div>
                    <div class="metrics">
                        <div class="metric"><span>Market Cap</span><span class="value">${tc.get('market_cap', 0):,.2f}</span></div>
                        <div class="metric"><span>Holders</span><span class="value">{tc.get('holder_count', 0):,}</span></div>
                    </div>
                    <div class="actions">
                        <a href="/coin/{tc['token_address']}" class="btn">Details</a>
                        <a href="/trade/{tc['token_address']}" class="btn btn-primary">Trade</a>
                        <button class="btn btn-copy" onclick="copyToClipboard('{tc['token_address']}', this)">📋 Copy Address</button>
                    </div>
                </div>""")

            trending_section = f"""
            <div class="trending-section">
                <h2>🔥 Trending Now (Fastest Growing)</h2>
                <div class="coins-grid">
                    {''.join(trending_html)}
                </div>
            </div>
            """

        return f"""
        <div class="coins-container">
            {twitter_section_html}
            {trending_section}
            <div class="filters">
                <button id="refreshBtn" class="btn btn-refresh" onclick="refreshCoins()">🔄 Refresh Coins</button>
                <input type="text" id="search" placeholder="Search coins..." value="{search}">
                <select id="sort" onchange="updateFilters()">
                    <option value="newest" {sort_newest}>Newest</option>
                    <option value="market_cap" {sort_mcap}>Highest Market Cap</option>
                    <option value="holders" {sort_holders}>Most Holders</option>
                    <option value="trending" {sort_trending}>🔥 Trending</option>
                    <option value="risk_low" {sort_low_risk}>Lowest Risk</option>
                    <option value="risk_high" {sort_high_risk}>Highest Risk</option>
                </select>
                <select id="freshness" onchange="updateFilters()">
                    <option value="all" {fresh_all}>All Coins</option>
                    <option value="new" {fresh_new}>🔥 Brand New (< 1h)</option>
                    <option value="recent" {fresh_recent}>⏰ Recent (< 24h)</option>
                    <option value="established" {fresh_established}>✓ Established (> 24h)</option>
                </select>
            </div>
            <div class="coins-grid">
                {cards or "<p>No coins found</p>"}
            </div>
        </div>

        <script>
        function refreshCoins() {{
            const btn = document.getElementById('refreshBtn');
            btn.disabled = true;
            btn.textContent = '⏳ Fetching...';

            fetch('/api/refresh-coins')
                .then(r => r.json())
                .then(data => {{
                    if (data.success) {{
                        btn.textContent = '✅ Updated!';
                        setTimeout(() => {{
                            location.reload();
                        }}, 1000);
                    }} else {{
                        btn.textContent = '❌ Failed';
                        setTimeout(() => {{
                            btn.textContent = '🔄 Refresh Coins';
                            btn.disabled = false;
                        }}, 2000);
                    }}
                }})
                .catch(err => {{
                    btn.textContent = '❌ Error';
                    setTimeout(() => {{
                        btn.textContent = '🔄 Refresh Coins';
                        btn.disabled = false;
                    }}, 2000);
                }});
        }}

        function updateFilters() {{
            const search = document.getElementById('search').value;
            const sort = document.getElementById('sort').value;
            const freshness = document.getElementById('freshness').value;
            window.location.href = '/coins?search=' + encodeURIComponent(search) + '&sort=' + sort + '&freshness=' + freshness;
        }}

        function addWatchlist(address) {{
            fetch('/watchlist/add/' + address, {{method: 'POST'}})
                .then(() => location.reload());
        }}

        function removeWatchlist(coinId) {{
            fetch('/watchlist/remove/' + coinId, {{method: 'POST'}})
                .then(() => location.reload());
        }}

        function copyToClipboard(address, button) {{
            // Try Clipboard API first
            if (navigator.clipboard && navigator.clipboard.writeText) {{
                navigator.clipboard.writeText(address).then(() => {{
                    showCopyFeedback(button);
                }}).catch(() => {{
                    fallbackCopy(address, button);
                }});
            }} else {{
                fallbackCopy(address, button);
            }}
        }}

        function fallbackCopy(text, button) {{
            const input = document.createElement('textarea');
            input.value = text;
            input.style.position = 'fixed';
            input.style.opacity = '0';
            document.body.appendChild(input);
            input.select();
            try {{
                document.execCommand('copy');
                showCopyFeedback(button);
            }} catch (err) {{
                // If all else fails, just show the address in alert
                alert('Address: ' + text + '\\n\\n(Unable to auto-copy, but address is shown above)');
            }}
            document.body.removeChild(input);
        }}

        function showCopyFeedback(button) {{
            const originalText = button.textContent;
            button.textContent = '✅ Copied!';
            button.classList.add('copied');
            setTimeout(() => {{
                button.textContent = originalText;
                button.classList.remove('copied');
            }}, 2000);
        }}
        </script>
        """

    def coin_detail(self, coin, analysis):
        return f"""
        <div class="coin-detail">
            <h1>{coin['name']} ({coin.get('symbol', '?')})</h1>

            <div class="detail-box">
                <h3>📈 7-Day Price History</h3>
                <canvas id="priceChart" style="max-height: 300px; margin-bottom: 2rem;"></canvas>
                <p id="chartStatus">Loading price history...</p>
            </div>

            <div class="detail-box">
                <h3>Market Data</h3>
                <p><strong>Market Cap:</strong> ${coin.get('market_cap', 0):,.2f}</p>
                <p><strong>Holders:</strong> {coin.get('holder_count', 0):,}</p>
                <p><strong>Token Address:</strong> <code>{coin['token_address']}</code></p>
                <p><a href="https://solscan.io/token/{coin['token_address']}" target="_blank" class="link">View on Solscan →</a></p>
            </div>

            <div class="detail-box">
                <h3>Risk Analysis</h3>
                <p><strong>Rug Pull Risk:</strong> {analysis.get('rug_pull_score', '?')}</p>
                <p><strong>Honeypot Risk:</strong> {analysis.get('honeypot_score', '?')}</p>
                <p><strong>Scam Risk:</strong> {analysis.get('scam_score', '?')}</p>
                <p><strong>Overall Score:</strong> {analysis.get('overall_risk_score', '?')}</p>
                <p><strong>Recommendation:</strong> {analysis.get('recommendation', '?')}</p>
                <p><strong>Notes:</strong> {analysis.get('analysis_notes', 'No notes')}</p>
            </div>

            <div class="action-buttons">
                <a href="/trade/{coin['token_address']}" class="btn btn-primary btn-lg">Trade Now</a>
                <a href="/coins" class="btn btn-lg">Back to Feed</a>
            </div>
        </div>

        <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"></script>
        <script>
        (async () => {{
            try {{
                const response = await fetch('/api/coin/{coin['token_address']}/history');
                const data = await response.json();

                if (!data.price_history || data.price_history.length === 0) {{
                    document.getElementById('chartStatus').textContent = 'No price history available yet (collecting data...)';
                    return;
                }}

                const labels = data.price_history.map(h => {{
                    const date = new Date(h.recorded_at);
                    return date.toLocaleTimeString();
                }});

                const prices = data.price_history.map(h => h.price);
                const marketCaps = data.price_history.map(h => h.market_cap);

                const ctx = document.getElementById('priceChart').getContext('2d');
                new Chart(ctx, {{
                    type: 'line',
                    data: {{
                        labels: labels,
                        datasets: [{{
                            label: 'Price (USD)',
                            data: prices,
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.1)',
                            borderWidth: 2,
                            tension: 0.4,
                            pointRadius: 3,
                            pointBackgroundColor: '#667eea'
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: true,
                        plugins: {{
                            legend: {{
                                labels: {{ color: '#fff' }}
                            }}
                        }},
                        scales: {{
                            y: {{
                                ticks: {{ color: '#aaa' }},
                                grid: {{ color: '#333' }}
                            }},
                            x: {{
                                ticks: {{ color: '#aaa' }},
                                grid: {{ color: '#333' }}
                            }}
                        }}
                    }}
                }});

                document.getElementById('chartStatus').style.display = 'none';
            }} catch (err) {{
                document.getElementById('chartStatus').textContent = 'Error loading price history: ' + err.message;
            }}
        }})();
        </script>
        """

    def trade_page(self, coin, analysis):
        return f"""
        <div class="trade-page">
            <h1>Trade {coin['symbol']}</h1>

            <div class="trade-options">
                <div class="option">
                    <h3>💱 Raydium</h3>
                    <p>Decentralized exchange on Solana</p>
                    <a href="https://raydium.io/swap/?inputCurrency=sol&outputCurrency={coin['token_address']}" target="_blank" class="btn btn-primary">Open Raydium</a>
                </div>

                <div class="option">
                    <h3>🔀 Jupiter</h3>
                    <p>Best price aggregator on Solana</p>
                    <a href="https://jup.ag/swap?inputMint=So11111111111111111111111111111111111111112&outputMint={coin['token_address']}" target="_blank" class="btn btn-primary">Open Jupiter</a>
                </div>
            </div>

            <div style="background: #1a1f3a; padding: 2rem; border-radius: 8px; margin: 2rem 0;">
                <h3>🔐 Phantom Wallet</h3>
                <p id="walletInfo" style="color: #aaa; margin-bottom: 1rem;">Connect your Phantom wallet to track balances and trades</p>
                <button id="tradeWalletBtn" class="btn btn-primary">Connect Phantom Wallet</button>
                <span id="tradeWalletStatus" style="margin-left: 1rem; color: #10b981; display: none;">
                    ✓ Connected: <span id="tradeWalletAddr" style="font-family: monospace;"></span>
                </span>
            </div>

            <div class="risk-box">
                <h3>Risk Assessment</h3>
                <p><strong>Overall Risk:</strong> {analysis.get('overall_risk_score', '?')}</p>
                <p><strong>Recommendation:</strong> {analysis.get('recommendation', 'HOLD')}</p>
                <p>{analysis.get('analysis_notes', 'No major issues detected')}</p>
            </div>

            <a href="/coins" class="btn">Back to Feed</a>
        </div>

        <script>
        document.getElementById('tradeWalletBtn').addEventListener('click', function() {{
            const saved = localStorage.getItem('phantomWallet');
            if (saved) {{
                const btn = document.getElementById('tradeWalletBtn');
                const status = document.getElementById('tradeWalletStatus');
                const addr = document.getElementById('tradeWalletAddr');
                btn.style.display = 'none';
                status.style.display = 'inline';
                addr.textContent = saved.substring(0, 8) + '...' + saved.substring(saved.length - 6);
            }} else {{
                alert('Wallet not connected. Use the button in the header to connect first.');
            }}
        }});

        // Check if already connected
        window.addEventListener('load', function() {{
            const saved = localStorage.getItem('phantomWallet');
            if (saved) {{
                const btn = document.getElementById('tradeWalletBtn');
                const status = document.getElementById('tradeWalletStatus');
                const addr = document.getElementById('tradeWalletAddr');
                btn.style.display = 'none';
                status.style.display = 'inline';
                addr.textContent = saved.substring(0, 8) + '...' + saved.substring(saved.length - 6);
            }}
        }});
        </script>
        """

    def dashboard_page(self, user, watchlist, trades, analyses):
        watchlist_value = sum(c.get('market_cap', 0) for c in watchlist)

        watchlist_html = ''.join([
            f"""<div class="dashboard-coin">
                <div>
                    <h4>{c['name']}</h4>
                    <p class="symbol">{c.get('symbol', '?')}</p>
                </div>
                <div class="metrics">
                    <p class="price">${c.get('market_cap', 0):,.2f}</p>
                    <p class="holders">{c.get('holder_count', 0)} holders</p>
                </div>
                <div class="actions">
                    <a href="/coin/{c['token_address']}" class="btn btn-small">View</a>
                    <button class="btn btn-small btn-danger" onclick="removeWatchlist({c['id']})">Remove</button>
                </div>
            </div>"""
            for c in watchlist
        ]) or '<p>No coins in watchlist yet</p>'

        trades_html = ''.join([
            f"""<tr>
                <td>{t['action'].upper()}</td>
                <td>{t['amount_sol'] or 0} SOL</td>
                <td>{t['profit_loss_sol'] or '-'}</td>
                <td>{t['traded_at'][:10]}</td>
            </tr>"""
            for t in trades[:10]
        ]) or '<tr><td colspan="4">No trades yet</td></tr>'

        return f"""
        <div class="dashboard">
            <h1>👤 {user['name']}'s Dashboard</h1>

            <div class="dashboard-grid">
                <div class="stat-box">
                    <h3>Watchlist Value</h3>
                    <p class="stat-value">${watchlist_value:,.2f}</p>
                    <p class="stat-label">{len(watchlist)} coins</p>
                </div>

                <div class="stat-box">
                    <h3>Total Trades</h3>
                    <p class="stat-value">{len(trades)}</p>
                    <p class="stat-label">All time</p>
                </div>
            </div>

            <div class="dashboard-section">
                <h2>📋 My Watchlist</h2>
                <div class="watchlist-grid">
                    {watchlist_html}
                </div>
            </div>

            <div class="dashboard-section">
                <h2>📊 Recent Trades</h2>
                <table class="trades-table">
                    <thead>
                        <tr>
                            <th>Action</th>
                            <th>Amount</th>
                            <th>P&L</th>
                            <th>Date</th>
                        </tr>
                    </thead>
                    <tbody>
                        {trades_html}
                    </tbody>
                </table>
            </div>

            <div class="action-buttons">
                <a href="/coins" class="btn btn-primary">Browse Coins</a>
                <a href="/logout" class="btn">Log Out</a>
            </div>
        </div>

        <script>
        function removeWatchlist(coinId) {{
            fetch('/watchlist/remove/' + coinId, {{method: 'POST'}})
                .then(() => location.reload());
        }}

        function copyToClipboard(address, button) {{
            // Try Clipboard API first
            if (navigator.clipboard && navigator.clipboard.writeText) {{
                navigator.clipboard.writeText(address).then(() => {{
                    showCopyFeedback(button);
                }}).catch(() => {{
                    fallbackCopy(address, button);
                }});
            }} else {{
                fallbackCopy(address, button);
            }}
        }}

        function fallbackCopy(text, button) {{
            const input = document.createElement('textarea');
            input.value = text;
            input.style.position = 'fixed';
            input.style.opacity = '0';
            document.body.appendChild(input);
            input.select();
            try {{
                document.execCommand('copy');
                showCopyFeedback(button);
            }} catch (err) {{
                // If all else fails, just show the address in alert
                alert('Address: ' + text + '\\n\\n(Unable to auto-copy, but address is shown above)');
            }}
            document.body.removeChild(input);
        }}

        function showCopyFeedback(button) {{
            const originalText = button.textContent;
            button.textContent = '✅ Copied!';
            button.classList.add('copied');
            setTimeout(() => {{
                button.textContent = originalText;
                button.classList.remove('copied');
            }}, 2000);
        }}
        </script>
        """

    def watchlist_page(self, coins, analyses, user):
        cards = ''.join([
            f"""<div class="coin-card">
                <h3>{c['name']}</h3>
                <p class="symbol">{c.get('symbol', '?')}</p>
                <p><strong>${c.get('market_cap', 0):,.2f}</strong> market cap</p>
                <p>{c.get('holder_count', 0):,} holders</p>
                <div class="actions">
                    <a href="/coin/{c['token_address']}" class="btn">Details</a>
                    <a href="/trade/{c['token_address']}" class="btn btn-primary">Trade</a>
                </div>
            </div>"""
            for c in coins
        ]) or '<p>No coins in your watchlist yet. <a href="/coins">Browse coins</a></p>'

        return f"""
        <div class="watchlist">
            <h1>❤️ My Watchlist</h1>
            <div class="coins-grid">{cards}</div>
            <a href="/coins" class="btn">Add More Coins</a>
        </div>
        """

    def login_page(self, error=""):
        error_html = f'<div class="error">{error}</div>' if error else ""
        return f"""
        <div class="auth-form">
            <h2>Log In</h2>
            {error_html}
            <form method="post">
                <input type="email" name="email" placeholder="Email" required>
                <input type="password" name="password" placeholder="Password" required>
                <button type="submit" class="btn btn-primary">Log In</button>
            </form>
            <p>Don't have an account? <a href="/signup">Sign up</a></p>
        </div>
        """

    def signup_page(self, error=""):
        error_html = f'<div class="error">{error}</div>' if error else ""
        return f"""
        <div class="auth-form">
            <h2>Create Account</h2>
            {error_html}
            <form method="post">
                <input type="text" name="name" placeholder="Full Name" required>
                <input type="email" name="email" placeholder="Email" required>
                <input type="password" name="password" placeholder="Password" required>
                <button type="submit" class="btn btn-primary">Sign Up</button>
            </form>
            <p>Already have an account? <a href="/login">Log in</a></p>
        </div>
        """

    def render(self, title, body):
        user = self.get_user()
        nav_items = []

        # Wallet connection
        wallet_html = ""
        if user:
            wallet_html = f"""
            <div id="wallet-section" style="display: inline-block; margin-right: 2rem;">
                <button id="connectWalletBtn" class="btn btn-primary" style="padding: 0.5rem 1rem; font-size: 0.9rem;">
                    🔌 Connect Wallet
                </button>
                <span id="walletStatus" style="margin-left: 1rem; color: #10b981; display: none;">
                    ✓ Connected: <span id="walletAddr" style="font-family: monospace; font-size: 0.8rem;"></span>
                </span>
            </div>
            """

        if user:
            nav_items.append(f'<a href="/dashboard">Dashboard</a>')
            nav_items.append(f'<a href="/me/watchlist">Watchlist</a>')
            nav_items.append(f'<span>{user["name"]}</span>')
            nav_items.append(f'<a href="/logout">Log out</a>')
        else:
            nav_items.append('<a href="/login">Log In</a>')
            nav_items.append('<a href="/signup">Sign Up</a>')

        nav = ' | '.join(nav_items)

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} - Pump Trader</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0a0e27; color: #fff; line-height: 1.6; }}
        header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 1rem 2rem; }}
        header h1 {{ font-size: 1.5rem; margin: 0; }}
        nav {{ text-align: right; color: #fff; font-size: 0.9rem; }}
        nav a {{ color: #fff; text-decoration: none; margin: 0 1rem; }}
        nav a:hover {{ text-decoration: underline; }}
        main {{ max-width: 1200px; margin: 2rem auto; padding: 0 2rem; }}
        h1, h2, h3 {{ margin: 1rem 0 0.5rem; }}
        .subtitle {{ color: #aaa; font-size: 1.1rem; margin-bottom: 2rem; }}
        .filters {{ display: flex; gap: 1rem; margin-bottom: 2rem; align-items: center; flex-wrap: wrap; }}
        .filters input, .filters select {{ padding: 0.75rem; background: #1a1f3a; color: #fff; border: 1px solid #667eea; border-radius: 4px; flex: 1; min-width: 150px; }}
        .filters .btn-refresh {{ flex: 0 0 auto; margin: 0; }}
        .coins-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1.5rem; }}
        .coin-card {{ background: #1a1f3a; border-left: 4px solid #667eea; padding: 1.5rem; border-radius: 8px; }}
        .coin-card.risk-low {{ border-left-color: #10b981; }}
        .coin-card.risk-medium {{ border-left-color: #f59e0b; }}
        .coin-card.risk-high {{ border-left-color: #ef4444; }}
        .coin-header {{ display: flex; justify-content: space-between; align-items: start; margin-bottom: 1rem; }}
        .symbol {{ color: #aaa; font-size: 0.9rem; }}
        .risk-badge {{ background: #667eea; padding: 0.5rem 1rem; border-radius: 4px; font-weight: bold; }}
        .safety-box {{ padding: 0.75rem 1rem; border-radius: 8px; text-align: center; min-width: 80px; box-shadow: 0 2px 8px rgba(0,0,0,0.3); }}
        .safety-percent {{ font-size: 1.8rem; font-weight: bold; color: #fff; line-height: 1; }}
        .safety-label {{ font-size: 0.7rem; color: rgba(255,255,255,0.9); text-transform: uppercase; letter-spacing: 1px; margin-top: 0.25rem; }}
        .twitter-data {{ background: #0a1929; border-left: 3px solid #1da1f2; padding: 0.75rem; border-radius: 4px; margin: 0.75rem 0; }}
        .twitter-label {{ color: #1da1f2; font-size: 0.85rem; font-weight: bold; margin-bottom: 0.5rem; }}
        .twitter-stats {{ display: flex; gap: 0.75rem; font-size: 0.8rem; }}
        .twitter-stat {{ color: #aaa; }}
        .twitter-stat strong {{ color: #1da1f2; font-weight: bold; }}
        .metrics {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin: 1rem 0; }}
        .metric {{ background: #0a0e27; padding: 0.75rem; border-radius: 4px; }}
        .metric span {{ display: block; }}
        .metric .value {{ color: #667eea; font-size: 1.2rem; font-weight: bold; }}
        .actions {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
        .btn {{ padding: 0.75rem 1.5rem; background: #667eea; color: #fff; border: none; border-radius: 4px; cursor: pointer; text-decoration: none; display: inline-block; transition: background 0.2s; }}
        .btn:hover {{ background: #764ba2; }}
        .btn-primary {{ background: #10b981; }}
        .btn-primary:hover {{ background: #059669; }}
        .btn-watchlist {{ padding: 0.5rem 1rem; font-size: 0.85rem; }}
        .btn-small {{ padding: 0.5rem 1rem; font-size: 0.85rem; }}
        .btn-copy {{ background: #8b5cf6; padding: 0.6rem 1rem; font-size: 0.9rem; }}
        .btn-copy:hover {{ background: #7c3aed; }}
        .btn-copy.copied {{ background: #10b981; }}
        .btn-refresh {{ background: #06b6d4; padding: 0.75rem 1.5rem; font-size: 0.95rem; font-weight: 600; }}
        .btn-refresh:hover {{ background: #0891b2; }}
        .btn-refresh:disabled {{ background: #64748b; cursor: not-allowed; opacity: 0.7; }}
        .btn-danger {{ background: #ef4444; }}
        .btn-danger:hover {{ background: #dc2626; }}
        .btn-lg {{ padding: 1rem 2rem; font-size: 1.1rem; }}
        .featured-coins {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 1rem; margin: 2rem 0; }}
        .cta {{ text-align: center; margin: 3rem 0; }}
        .cta .btn {{ margin: 0 0.5rem; }}
        .trade-options {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; margin: 2rem 0; }}
        .option {{ background: #1a1f3a; padding: 2rem; border-radius: 8px; text-align: center; }}
        .option h3 {{ margin: 0 0 1rem; }}
        .auth-form {{ max-width: 400px; margin: 3rem auto; background: #1a1f3a; padding: 2rem; border-radius: 8px; }}
        .auth-form input {{ width: 100%; padding: 0.75rem; margin: 1rem 0; border: none; border-radius: 4px; background: #0a0e27; color: #fff; }}
        .auth-form button {{ width: 100%; margin-top: 1rem; }}
        .error {{ background: #ef4444; padding: 1rem; border-radius: 4px; margin-bottom: 1rem; }}
        .link {{ color: #667eea; text-decoration: none; }}
        .link:hover {{ text-decoration: underline; }}
        code {{ background: #0a0e27; padding: 0.25rem 0.5rem; border-radius: 3px; font-size: 0.9rem; }}
        .dashboard-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1.5rem; margin: 2rem 0; }}
        .stat-box {{ background: #1a1f3a; padding: 2rem; border-radius: 8px; text-align: center; border-left: 4px solid #667eea; }}
        .stat-value {{ font-size: 2.5rem; font-weight: bold; color: #10b981; margin: 1rem 0; }}
        .stat-label {{ color: #aaa; }}
        .dashboard-section {{ background: #1a1f3a; padding: 2rem; border-radius: 8px; margin: 2rem 0; }}
        .dashboard-coin {{ background: #0a0e27; padding: 1.5rem; border-radius: 8px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }}
        .watchlist-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1rem; margin: 1rem 0; }}
        .trades-table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
        .trades-table th, .trades-table td {{ padding: 1rem; text-align: left; border-bottom: 1px solid #667eea; }}
        .trades-table th {{ background: #0a0e27; font-weight: bold; }}
        .action-buttons {{ display: flex; gap: 1rem; margin-top: 2rem; }}
        .freshness-badge {{ display: inline-block; margin-left: 0.5rem; padding: 0.25rem 0.75rem; border-radius: 20px; font-size: 0.8rem; font-weight: bold; }}
        .freshness-new {{ background: #dc2626; color: #fff; }}
        .freshness-recent {{ background: #f59e0b; color: #fff; }}
        .freshness-established {{ background: #6b7280; color: #fff; }}
        .trending-section {{ margin-bottom: 3rem; padding-bottom: 2rem; border-bottom: 2px solid #667eea; }}
        .trending-section h2 {{ color: #10b981; font-size: 1.5rem; margin-bottom: 1.5rem; }}
    </style>
</head>
<body>
    <header>
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <h1>🚀 Pump Trader</h1>
            <div style="display: flex; align-items: center; gap: 2rem;">
                {wallet_html}
                <nav>{nav}</nav>
            </div>
        </div>
    </header>
    <main>{body}</main>

    <script src="https://github.com/phantom-app/phantom-sdk/releases/latest/download/phantom.js"></script>
    <script>
    // Phantom Wallet Integration
    async function connectWallet() {{
        const {{ solana }} = window;

        if (!solana) {{
            alert('Phantom wallet not installed. Visit https://phantom.app');
            return;
        }}

        try {{
            const response = await solana.connect();
            const publicKey = response.publicKey.toString();

            // Store wallet address
            localStorage.setItem('phantomWallet', publicKey);

            // Send to backend
            fetch('/api/wallet/connect', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{ wallet_address: publicKey }})
            }}).then(r => r.json()).then(data => {{
                if (data.ok) {{
                    displayWalletStatus(publicKey);
                }}
            }});

        }} catch (err) {{
            console.error('Wallet connection failed:', err);
            alert('Failed to connect wallet: ' + err.message);
        }}
    }}

    function displayWalletStatus(address) {{
        const btn = document.getElementById('connectWalletBtn');
        const status = document.getElementById('walletStatus');
        const addr = document.getElementById('walletAddr');

        if (btn && status && addr) {{
            btn.style.display = 'none';
            status.style.display = 'inline';
            addr.textContent = address.substring(0, 8) + '...' + address.substring(address.length - 6);
        }}
    }}

    // Check if wallet already connected
    document.addEventListener('DOMContentLoaded', function() {{
        const saved = localStorage.getItem('phantomWallet');
        if (saved) {{
            displayWalletStatus(saved);
        }}

        const btn = document.getElementById('connectWalletBtn');
        if (btn) {{
            btn.addEventListener('click', connectWallet);
        }}
    }});
    </script>
</body>
</html>"""
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode())

    def json_response(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def redirect(self, path, cookie_name=None, cookie_value=None):
        self.send_response(302)
        if cookie_name and cookie_value:
            self.send_header('Set-Cookie', f'{cookie_name}={cookie_value}; Path=/')
        self.send_header('Location', path)
        self.end_headers()

    def not_found(self):
        self.render("Not Found", "<h1>404 - Page not found</h1>")

    def set_cookie(self, name, value, max_age=None):
        if max_age == 0:
            self.send_header('Set-Cookie', f'{name}=; Max-Age=0; Path=/')
        else:
            self.send_header('Set-Cookie', f'{name}={value}; Path=/')

    def get_user(self):
        cookies = self.headers.get('Cookie', '')
        for cookie in cookies.split(';'):
            if 'session=' in cookie:
                token = cookie.split('=')[1].strip()
                session = models.get_session(token)
                if session:
                    return models.get_user_by_id(session['user_id'])
        return None

    def risk_level(self, score):
        if score is None:
            score = 0.5
        if score < 0.3:
            return "low"
        elif score < 0.6:
            return "medium"
        else:
            return "high"

    def coin_freshness(self, coin):
        """Calculate coin age and return freshness badge"""
        try:
            discovered = datetime.fromisoformat(coin['discovered_at'])
            age_seconds = (datetime.now() - discovered).total_seconds()
            age_minutes = int(age_seconds / 60)
            age_hours = int(age_seconds / 3600)

            if age_seconds < 3600:  # < 1 hour
                return ("NEW", "🔥", f"{age_minutes}m ago")
            elif age_seconds < 86400:  # < 24 hours
                return ("RECENT", "⏰", f"{age_hours}h ago")
            else:
                days = int(age_seconds / 86400)
                return ("ESTABLISHED", "", f"{days}d ago")
        except:
            return ("", "", "")


def main():
    db.init_db()
    start_monitor(interval_seconds=15)
    start_price_monitor(interval_seconds=8)
    start_alert_monitor(interval_seconds=60)
    # Twitter monitor requires Twitter API bearer token - set via environment variable
    # For now, it will warn if no token is configured
    start_twitter_monitor(bearer_token=None)

    print(f"🚀 Pump Trader running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop")
    print("\n💡 To enable Twitter tracking, set TWITTER_BEARER_TOKEN environment variable")

    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        stop_monitor()
        stop_price_monitor()
        stop_alert_monitor()
        stop_twitter_monitor()
        print("\n✓ Stopped")


if __name__ == '__main__':
    main()
