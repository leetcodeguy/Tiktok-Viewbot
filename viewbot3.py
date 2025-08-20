#!/usr/bin/env python3
import threading
import time
import random
import string
import os
import sys
import subprocess
import uuid
import requests
from stem import Signal
from stem.control import Controller

# Attempt to import Playwright, install on-the-fly if missing
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except ModuleNotFoundError:
    print("[Setup] Playwright not found. Installing...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    print("[Setup] Installing browser binaries...")
    subprocess.check_call([sys.executable, "-m", "playwright", "install"])

# ——— Configuration ———
TARGET_URL           = "https://www.tiktok.com/@_art_is_fast_/video/7526249060282486047"
THREAD_COUNT         = 20      # lower if still throttled
REQUESTS_PER_THREAD  = 1000
TOR_SOCKS_PORT       = 9050
TOR_CONTROL_PORT     = 9051

# rotate Tor identity every N requests
ROTATE_FREQ          = 1

# delay settings (seconds)
DELAY_MIN            = 2
DELAY_MAX            = 5
BACKOFF_MIN          = 10
BACKOFF_MAX          = 20

# optional cookies file
COOKIE_FILE = 'cookies.txt'
if os.path.exists(COOKIE_FILE):
    with open(COOKIE_FILE) as f:
        COOKIES = [line.strip() for line in f if line.strip()]
else:
    COOKIES = None

# sample mobile User-Agent pool for a clean mobile fingerprint
MOBILE_USER_AGENTS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPad; CPU OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Mobile Safari/537.36"
]
# Accept-Language pool
LANGUAGES = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.8",
    "fr-FR,fr;q=0.9,en;q=0.8",
    "de-DE,de;q=0.9,en;q=0.8"
]

# referer pool or base referer
REFERERS = [
    "https://www.tiktok.com/",
    TARGET_URL
]

USE_PLAYWRIGHT = True  # Set to False to disable JS "view" event wait
PLAYWRIGHT_TIMEOUT_MS = 30_000  # navigation & function wait timeout

# ——— Utility Functions ———

def gen_random_cookie():
    val = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    return f"sessionid={val}"

def get_tor_session():
    s = requests.Session()
    s.proxies = {
        'http':  f'socks5h://127.0.0.1:{TOR_SOCKS_PORT}',
        'https': f'socks5h://127.0.0.1:{TOR_SOCKS_PORT}',
    }
    return s

def renew_tor_identity():
    with Controller.from_port(port=TOR_CONTROL_PORT) as ctl:
        ctl.authenticate()
        exits = [r for r in ctl.get_network_statuses() if 'Exit' in r.flags]
        choice = random.choice(exits)
        ctl.set_conf('ExitNodes', f'${choice.fingerprint}')
        ctl.set_conf('StrictNodes', '1')
        ctl.signal(Signal.NEWNYM)
        time.sleep(random.uniform(1, 3))

# Playwright-based function to wait for JS "view" event

def fire_view_event(url: str, timeout: int = PLAYWRIGHT_TIMEOUT_MS):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            proxy={'server': f'socks5://127.0.0.1:{TOR_SOCKS_PORT}'}
        )
        context = browser.new_context(
            user_agent=random.choice(MOBILE_USER_AGENTS),
            viewport={"width": 375, "height": 667},  # typical mobile viewport
            locale="en-US",
            java_script_enabled=True,
        )
        # bump global timeout for navigation
        context.set_default_navigation_timeout(timeout)
        page = context.new_page()

        # block heavy resources to speed up networkidle
        page.route("**/*", lambda route, req: route.abort() if req.resource_type in ["image", "stylesheet", "font"] else route.continue_())

        page.goto(url, wait_until="networkidle", timeout=timeout)

        try:
            page.wait_for_function("window.__viewEventFired === true", timeout=timeout)
            print(f"[Playwright] ✅ View event fired for {url}")
        except PlaywrightTimeoutError:
            print(f"[Playwright] ⚠️ Timeout ({timeout}ms) waiting for view event on {url}")
        finally:
            browser.close()

# ——— Worker Thread ———

def worker(tid):
    session = get_tor_session()
    for i in range(1, REQUESTS_PER_THREAD + 1):
        try:
            if i % ROTATE_FREQ == 0:
                renew_tor_identity()

            # generate per-request mobile-style fingerprint
            device_id = uuid.uuid4().hex
            cookie = random.choice(COOKIES) if COOKIES else gen_random_cookie()
            ua     = random.choice(MOBILE_USER_AGENTS)
            lang   = random.choice(LANGUAGES)
            referer= random.choice(REFERERS)
            headers = {
                'Cookie': cookie,
                'User-Agent': ua,
                'Accept-Language': lang,
                'Referer': referer,
                'X-Device-ID': device_id
            }

            resp = session.get(TARGET_URL, timeout=30, headers=headers)
            print(f"[T{tid}] {i}/{REQUESTS_PER_THREAD} → {resp.status_code} (UA: {ua.split(' ')[0]}..., Cookie: {cookie}, DevID: {device_id[:8]})")

            if USE_PLAYWRIGHT and resp.status_code == 200:
                fire_view_event(TARGET_URL)

            if resp.status_code == 403:
                wait = random.uniform(BACKOFF_MIN, BACKOFF_MAX)
                print(f"[T{tid}] 403 → backing off {wait:.1f}s")
                time.sleep(wait)
            else:
                time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

        except Exception as e:
            print(f"[T{tid}] error: {e}")
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    print(f"[T{tid}] done.")

# ——— Main ———

def main():
    threads = []
    for n in range(1, THREAD_COUNT + 1):
        t = threading.Thread(target=worker, args=(n,), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    print("All done.")

if __name__ == "__main__":
    main()

