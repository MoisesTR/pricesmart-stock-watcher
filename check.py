#!/usr/bin/env python3
"""
PriceSmart stock watcher.

Loads each product page in a real headless browser (PriceSmart renders the
product detail client-side, so a plain HTTP request only sees an empty shell),
figures out whether it's in stock, and pings Telegram when something that was
unavailable becomes available again.

State (last seen status per product) is kept in state.json so we only alert on
the *transition* into stock, not on every run.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
PRODUCTS_FILE = ROOT / "products.json"
STATE_FILE = ROOT / "state.json"

TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT = os.environ.get("TG_CHAT")
# Set DEBUG_NOTIFY=1 for the first couple of runs to receive the raw detection
# evidence on Telegram so you can confirm the in/out-of-stock signal is right.
DEBUG_NOTIFY = os.environ.get("DEBUG_NOTIFY") == "1"

# --- Detection tuning -------------------------------------------------------
# What PriceSmart shows when a product is NOT purchasable (verified on the live
# site). Lowercase. "fuera de stock" is the real one; the rest are safety nets.
OUT_OF_STOCK_MARKERS = [
    "fuera de stock",
    "no disponible",
    "agotado",
    "sin existencia",
    "producto no disponible",
    "temporalmente sin stock",
]
# Text that proves the product detail section actually rendered. If this is
# absent, the page didn't load properly -> report "unknown" rather than risk a
# false "in stock" alert. Appears on every product page (lowercased).
LOADED_MARKER = "número de ítem"
# The buy button label (extra positive evidence when in stock). If a button
# with this label is visible AND enabled, the product is purchasable.
ADD_TO_CART_RE = re.compile(r"agregar al carrito|añadir al carrito|add to cart", re.I)
# ---------------------------------------------------------------------------


def notify(text: str) -> None:
    if not (TG_TOKEN and TG_CHAT):
        print("  [notify skipped: TG_TOKEN/TG_CHAT not set]")
        return
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            params={"chat_id": TG_CHAT, "text": text, "disable_web_page_preview": False},
            timeout=20,
        )
        if r.status_code != 200:
            print(f"  [telegram error {r.status_code}: {r.text[:200]}]")
    except requests.RequestException as e:
        print(f"  [telegram request failed: {e}]")


def detect_status(page):
    """Return (status, evidence) where status is in_stock | out_of_stock | unknown."""
    body_text = ""
    try:
        body_text = page.inner_text("body", timeout=5000).lower()
    except Exception:
        pass

    # Look for a visible, enabled add-to-cart button (extra positive evidence).
    cart_button = False
    for btn in page.query_selector_all("button"):
        try:
            label = (btn.inner_text() or "").strip()
        except Exception:
            continue
        if label and ADD_TO_CART_RE.search(label):
            try:
                if btn.is_visible() and btn.is_enabled():
                    cart_button = True
                    break
            except Exception:
                continue

    loaded = LOADED_MARKER in body_text
    markers_found = [m for m in OUT_OF_STOCK_MARKERS if m in body_text]
    evidence = f"loaded={loaded}, cart_button={cart_button}, out_markers={markers_found or 'none'}"

    # If the product section never rendered, don't guess — say unknown.
    if not loaded:
        return "unknown", evidence
    # Product rendered with an out-of-stock notice -> out of stock.
    if markers_found:
        return "out_of_stock", evidence
    # Product rendered, no out-of-stock notice -> it's purchasable.
    return "in_stock", evidence


def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    return default


def main():
    products = load_json(PRODUCTS_FILE, [])
    if not products:
        print("No products configured in products.json")
        return 1

    state = load_json(STATE_FILE, {})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            locale="es-NI",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()

        for prod in products:
            pid, name, url = prod["id"], prod["name"], prod["url"]
            prev = state.get(pid, {}).get("status", "unknown")
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
                # wait for the client-side product detail to render
                try:
                    page.get_by_text("Número de ítem", exact=False).first.wait_for(
                        timeout=15000
                    )
                except Exception:
                    page.wait_for_timeout(3000)  # fall back to a short settle
                status, evidence = detect_status(page)
            except Exception as e:
                status, evidence = "unknown", f"error: {e}"

            print(f"[{pid}] {name}: {prev} -> {status}  ({evidence})")

            if DEBUG_NOTIFY:
                notify(f"🔎 DEBUG [{name}]\nstatus={status}\n{evidence}\n{url}")

            if status == "in_stock" and prev != "in_stock":
                notify(f"✅ ¡Disponible de nuevo!\n{name}\n{url}")

            state[pid] = {"status": status, "checked_at": now, "evidence": evidence}

        browser.close()

    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    print(f"State written to {STATE_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
