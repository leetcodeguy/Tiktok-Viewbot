#!/usr/bin/env python3
import sys, time, random, logging
from playwright.sync_api import sync_playwright, TimeoutError

# ——— CONFIG ———
PROXIES       = ["socks5://127.0.0.1:9050"]
UA_LIST       = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64)…Safari/537.36"]
OUTPUT_FILE   = "followers.txt"
MAX_STABLE_ROUNDS = 3

def scrape_followers(profile_url, proxies, user_agents):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    proxy = random.choice(proxies)
    ua    = random.choice(user_agents)
    logging.info(f"Proxy={proxy}  UA={ua}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[f"--proxy-server={proxy}", "--no-sandbox","--disable-setuid-sandbox"]
        )
        ctx = browser.new_context(user_agent=ua)
        page = ctx.new_page()

        try:
            page.goto(profile_url, timeout=60000)

            # dismiss cookie banner if it shows up
            for btn in ("button:has-text('Accept')","button:has-text('I Agree')"):
                try:
                    page.click(btn, timeout=3000)
                    logging.info("Cookie banner dismissed")
                    break
                except TimeoutError:
                    pass

            # try clicking the Followers tab
            try:
                fld = page.locator("span:has-text('Followers')")
                fld.scroll_into_view_if_needed(timeout=5000)
                fld.click(timeout=5000)
                logging.info("Clicked Followers")
            except TimeoutError:
                logging.warning("Followers tab not found; proceeding anyway")

            # wait briefly for any entry to appear
            try:
                page.wait_for_selector("div.user-item", timeout=10000)
            except TimeoutError:
                logging.warning("No follower items detected; will still attempt scrolling")

            # find the first scrollable parent of a user-item, else default to full page
            container = page
            handles = page.query_selector_all("div.user-item")
            if handles:
                for h in handles:
                    parent = h.evaluate_handle("el=>el.parentElement")
                    # walk up until you find overflow:auto or scroll
                    while parent:
                        ov = parent.evaluate("e=>getComputedStyle(e).overflowY")
                        if ov in ("auto","scroll"):
                            container = parent
                            logging.info("Using detected scroll container")
                            break
                        parent = parent.evaluate_handle("el=>el.parentElement")
                    if container is not page:
                        break
            else:
                logging.info("No user-item elements to inspect; using full-page scroll")

            # infinite scroll + stability check
            last, stable = 0, 0
            while True:
                if container == page:
                    page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                else:
                    container.evaluate("el=>el.scrollTo(0, el.scrollHeight)")
                time.sleep(random.uniform(1.5,3.0))

                # recount handles under that container
                sel    = "div.user-item div.username"
                count  = container.query_selector_all(sel)
                n      = len(count)
                logging.info(f"Handles loaded: {n}")

                if n == last:
                    stable += 1
                    if stable >= MAX_STABLE_ROUNDS:
                        break
                else:
                    stable, last = 0, n

            # extract & save
            usernames = [el.inner_text().strip() for el in container.query_selector_all("div.user-item div.username")]
            with open(OUTPUT_FILE, "w") as fd:
                fd.write("\n".join(usernames))
            logging.info(f"Scraped {len(usernames)} followers → {OUTPUT_FILE}")

        except TimeoutError as e:
            logging.error(f"TimeoutError: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    if len(sys.argv)!=2:
        print(f"Usage: {sys.argv[0]} <tiktok_profile_url>")
        sys.exit(1)
    scrape_followers(sys.argv[1], PROXIES, UA_LIST)

