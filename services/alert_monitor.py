"""Background service to monitor alerts and record coin prices/holders."""
import threading
import time
import db
import models


class AlertMonitor:
    """Background service to check alerts and record price history"""

    def __init__(self, check_interval_seconds=60):
        self.interval = check_interval_seconds
        self.running = False
        self.thread = None

    def start(self):
        """Start background monitoring"""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        print(f"[AlertMonitor] Started (interval: {self.interval}s)")

    def stop(self):
        """Stop background monitoring"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print("[AlertMonitor] Stopped")

    def _run(self):
        """Main loop: record prices and check alerts"""
        while self.running:
            try:
                self._record_prices()
                self._check_all_alerts()
            except Exception as e:
                print(f"[AlertMonitor] Error: {e}")

            time.sleep(self.interval)

    def _record_prices(self):
        """Record current prices and holders for all coins"""
        try:
            conn = db.connect()
            coins = conn.execute("SELECT id, market_cap, holder_count FROM coins WHERE holder_count > 0").fetchall()

            for coin in coins:
                models.record_price(
                    coin['id'],
                    price=0,  # Price tracking would require real data
                    market_cap=coin['market_cap'],
                    holder_count=coin['holder_count']
                )

            conn.close()
            print(f"[AlertMonitor] Recorded prices for {len(coins)} coins")
        except Exception as e:
            print(f"[AlertMonitor] Price recording error: {e}")

    def _check_all_alerts(self):
        """Check all active alerts and trigger if conditions met"""
        try:
            conn = db.connect()
            alerts = conn.execute("SELECT id FROM alert_thresholds WHERE is_active = 1").fetchall()

            triggered_count = 0
            for alert in alerts:
                if models.check_alert_conditions(alert['id']):
                    # Record that alert was triggered
                    conn.execute(
                        "INSERT INTO alert_history (alert_id, triggered_value, notified) VALUES (?, ?, 0)",
                        (alert['id'], None)
                    )
                    triggered_count += 1

            conn.commit()
            conn.close()

            if triggered_count > 0:
                print(f"[AlertMonitor] {triggered_count} alerts triggered")
        except Exception as e:
            print(f"[AlertMonitor] Alert check error: {e}")


# Global instance
_monitor = None


def start_monitor(interval_seconds=60):
    """Initialize and start the global monitor"""
    global _monitor
    if _monitor is None:
        _monitor = AlertMonitor(check_interval_seconds=interval_seconds)
    _monitor.start()


def stop_monitor():
    """Stop the global monitor"""
    global _monitor
    if _monitor:
        _monitor.stop()
