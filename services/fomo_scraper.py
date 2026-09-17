"""FOMO coin scraper - fetch real trending coins"""
import json
import re
import urllib.request
import urllib.error
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


class FOScraper:
    """Scrape trending coins from FOMO website"""

    def __init__(self):
        self.base_url = "https://fomo.family"
        self.playwright = None
        self.browser = None

    def _start_browser(self):
        """Start Playwright browser"""
        if not self.playwright:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(headless=True, args=['--disable-gpu', '--no-sandbox'])

    def _stop_browser(self):
        """Stop Playwright browser"""
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def fetch_trending_coins(self, limit=50):
        """Fetch trending coins from FOMO - with improved reliability"""
        try:
            self._start_browser()
            page = self.browser.new_page()
            page.set_default_timeout(8000)
            page.set_viewport_size({"width": 1920, "height": 1080})

            print("[FOScraper] Loading FOMO website...")
            try:
                page.goto(self.base_url, wait_until="domcontentloaded", timeout=10000)
                # Wait for content to load
                page.wait_for_timeout(2000)
            except Exception as e:
                print(f"[FOScraper] Page load warning: {e}")
                pass

            print("[FOScraper] Extracting coin data...")

            # Enhanced coin extraction with multiple selectors
            coin_data = page.evaluate("""
                () => {
                    const coins = [];
                    const seen = new Set();

                    // Try multiple selector strategies
                    const strategies = [
                        // Strategy 1: Look for token links
                        () => Array.from(document.querySelectorAll('a[href*="/token/"]')),
                        // Strategy 2: Look for coin containers
                        () => Array.from(document.querySelectorAll('[class*="coin"], [class*="token"]')),
                        // Strategy 3: Look for any link that might have token address
                        () => Array.from(document.querySelectorAll('a[href*="solana"]')),
                    ];

                    for (let strategy of strategies) {
                        try {
                            const elements = strategy();
                            for (let elem of elements) {
                                const href = elem.href || elem.getAttribute('href') || '';
                                if (!href) continue;

                                // Extract token address
                                let token = '';
                                const tokenMatch = href.match(/token\\/([a-zA-Z0-9]+)/i);
                                if (tokenMatch) {
                                    token = tokenMatch[1];
                                } else if (href.includes('solana') && href.length > 50) {
                                    // Try to extract from solana URL
                                    const addrMatch = href.match(/([a-zA-Z0-9]{43,})/);
                                    if (addrMatch) token = addrMatch[1];
                                }

                                if (!token || token.length < 20 || seen.has(token)) continue;
                                seen.add(token);

                                // Get text from element and parents
                                let text = elem.textContent || '';
                                let parent = elem.parentElement;
                                for (let i = 0; i < 3 && parent; i++) {
                                    text += ' ' + (parent.textContent || '');
                                    parent = parent.parentElement;
                                }

                                const lines = text.split('\\n').map(l => l.trim()).filter(l => l && l.length < 100);

                                let name = lines.find(l => l.length > 3 && l.length < 50 && !/^[\\$0-9%]/i.test(l)) || 'Token';
                                let symbol = lines.find(l => /^[A-Z0-9]{2,10}$/.test(l) && l.length < 10) || token.substring(0, 6);

                                coins.push({
                                    token: token,
                                    name: name,
                                    symbol: symbol,
                                    url: href
                                });

                                if (coins.length >= 50) break;
                            }
                            if (coins.length >= 20) break;
                        } catch (e) {
                            continue;
                        }
                    }

                    return coins;
                }
            """)

            coins = coin_data or []
            print(f"[FOScraper] Extracted {len(coins)} coins from FOMO page")

            page.close()
            return coins[:limit]

        except PlaywrightTimeoutError:
            print("[FOScraper] Timeout loading FOMO")
            return []
        except Exception as e:
            print(f"[FOScraper] Error: {e}")
            return []
        finally:
            self._stop_browser()

    def parse_coin(self, coin_data):
        """Parse raw FOMO coin data into standardized format"""
        try:
            token = coin_data.get('token', '')
            if not token:
                return None

            # Parse market cap
            mc_text = coin_data.get('market_cap', '0')
            market_cap = self._parse_number(mc_text)

            # Ensure minimum values
            if market_cap < 100:
                market_cap = max(100, market_cap)

            return {
                "token": token,
                "name": coin_data.get('name', 'Unknown'),
                "symbol": coin_data.get('symbol', '?'),
                "description": "",
                "creator": "",
                "url": coin_data.get('url', f"https://fomo.family/token/{token}"),
                "market_cap": market_cap,
                "holders": 1,
                "created_at": datetime.now().isoformat(),
                "image": ""
            }
        except Exception as e:
            print(f"[FOScraper] Parse error: {e}")
            return None

    def _parse_number(self, text):
        """Convert text with $, K, M, B suffixes to number"""
        if not text:
            return 0

        text = str(text).strip().upper()
        text = text.replace('$', '').strip()

        multipliers = {'K': 1000, 'M': 1000000, 'B': 1000000000}

        for suffix, mult in multipliers.items():
            if text.endswith(suffix):
                try:
                    num = float(text[:-1].strip())
                    return num * mult
                except:
                    return 0

        try:
            return float(text) if text else 0
        except:
            return 0


def fetch_fomo_coins(limit=50):
    """Public function to fetch FOMO coins"""
    scraper = FOScraper()
    raw_coins = scraper.fetch_trending_coins(limit=limit)

    coins = []
    for raw in raw_coins:
        coin = scraper.parse_coin(raw)
        if coin:
            coins.append(coin)

    print(f"[FOScraper] Successfully parsed {len(coins)} coins")
    return coins
