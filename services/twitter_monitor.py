"""Monitor Twitter/X for tweets about coins."""
import threading
import time
import urllib.request
import urllib.error
import json
import db
import models
from datetime import datetime


class TwitterMonitor:
    """Monitor tweets about meme coins."""

    def __init__(self, bearer_token=None):
        """Initialize with Twitter API bearer token."""
        self.bearer_token = bearer_token
        self.base_url = "https://api.twitter.com/2/tweets/search/recent"
        self.running = False
        self.thread = None

    def start(self):
        """Start background monitoring."""
        if self.running or not self.bearer_token or self.bearer_token == "YOUR_TWITTER_BEARER_TOKEN":
            if not self.bearer_token or self.bearer_token == "YOUR_TWITTER_BEARER_TOKEN":
                print("[TwitterMonitor] ⚠️  No Twitter API token configured - Twitter tracking disabled")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        print("[TwitterMonitor] Started (requires Twitter API token)")

    def stop(self):
        """Stop monitoring."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)

    def _run(self):
        """Main loop: monitor tweets."""
        while self.running:
            try:
                self._check_tweets()
            except Exception as e:
                print(f"[TwitterMonitor] Error: {e}")

            time.sleep(300)  # Check every 5 minutes

    def _check_tweets(self):
        """Check for tweets about tracked coins."""
        conn = db.connect()
        coins = conn.execute("SELECT id, name, symbol, token_address FROM coins LIMIT 10").fetchall()
        conn.close()

        for coin in coins:
            try:
                tweets = self._fetch_tweets_for_coin(coin)
                if tweets:
                    self._store_tweets(coin['id'], tweets)
            except Exception as e:
                continue

    def _fetch_tweets_for_coin(self, coin):
        """Fetch tweets mentioning a coin."""
        if not self.bearer_token:
            return []

        try:
            query = f"({coin['symbol']} OR {coin['name']}) -is:retweet"
            params = {
                "query": query,
                "max_results": 10,
                "tweet.fields": "public_metrics,created_at,author_id"
            }

            url = f"{self.base_url}?query={urllib.parse.quote(params['query'])}&max_results={params['max_results']}&tweet.fields={params['tweet.fields']}"

            headers = {
                "Authorization": f"Bearer {self.bearer_token}",
                "User-Agent": "MemeCoinTrader/1.0"
            }

            request = urllib.request.Request(url, headers=headers)

            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                return data.get("data", [])

        except urllib.error.HTTPError as e:
            if e.code == 401:
                print("[TwitterMonitor] ❌ Invalid API token")
            return []
        except Exception as e:
            return []

    def _store_tweets(self, coin_id, tweets):
        """Store tweet engagement data."""
        try:
            conn = db.connect()

            total_likes = 0
            total_retweets = 0
            total_replies = 0

            for tweet in tweets:
                metrics = tweet.get("public_metrics", {})
                total_likes += metrics.get("like_count", 0)
                total_retweets += metrics.get("retweet_count", 0)
                total_replies += metrics.get("reply_count", 0)

            # Store tweet engagement data
            conn.execute(
                """INSERT OR REPLACE INTO coin_twitter_data
                   (coin_id, tweet_count, total_likes, total_retweets, total_replies, checked_at)
                   VALUES (?, ?, ?, ?, ?, datetime('now'))""",
                (coin_id, len(tweets), total_likes, total_retweets, total_replies)
            )
            conn.commit()
            conn.close()

        except Exception as e:
            print(f"[TwitterMonitor] Store error: {e}")

    def get_twitter_data(self, coin_id):
        """Get stored Twitter data for a coin."""
        try:
            conn = db.connect()
            row = conn.execute(
                "SELECT tweet_count, total_likes, total_retweets, total_replies FROM coin_twitter_data WHERE coin_id = ?",
                (coin_id,)
            ).fetchone()
            conn.close()

            if row:
                return {
                    "tweets": row[0],
                    "likes": row[1],
                    "retweets": row[2],
                    "replies": row[3]
                }
        except:
            pass

        return None


# Global instance
_monitor = None


def start_monitor(bearer_token=None):
    """Start global Twitter monitor."""
    global _monitor
    if _monitor is None:
        _monitor = TwitterMonitor(bearer_token=bearer_token)
    _monitor.start()


def stop_monitor():
    """Stop global monitor."""
    global _monitor
    if _monitor:
        _monitor.stop()


def get_twitter_data(coin_id):
    """Get Twitter data for a coin."""
    global _monitor
    if _monitor:
        return _monitor.get_twitter_data(coin_id)
    return None
