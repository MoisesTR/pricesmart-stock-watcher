# PriceSmart stock watch

Checks PriceSmart product pages every 30 minutes and sends a **Telegram** message
when a product that was unavailable comes back in stock. Runs entirely on **GitHub
Actions** — no server to manage.

## How it works

PriceSmart's product pages render the price / stock / buy button **in the browser**
(client-side, via Bloomreach), so a plain HTTP request only sees an empty shell.
This watcher therefore loads each page in a real headless browser ([Playwright])
and reads the actual rendered state:

- a visible, **enabled** "Agregar al carrito" button → **in stock**
- an "No disponible" / "Agotado" marker and no buy button → **out of stock**

Last-seen status per product is cached between runs, so you only get pinged on the
**transition into stock**, not every 30 minutes.

Products watched are listed in [`products.json`](products.json) — edit that file to
add/remove items (each needs `id`, `name`, `url`).

## One-time setup

### 1. Create a Telegram bot + get your chat id

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`, follow
   the prompts. It gives you a **bot token** (looks like `123456:ABC-DEF...`).
2. Open a chat with your new bot and send it any message (e.g. `hi`). This is
   required — bots can't message you until you message them first.
3. Get your **chat id** by visiting this URL in a browser (paste your token):
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
   Look for `"chat":{"id":<NUMBER>` — that number is your chat id.

### 2. Push this repo to GitHub

```bash
gh repo create pricesmart-stock-watch --private --source=. --push
# or create the repo on github.com and: git remote add origin ... && git push -u origin main
```

### 3. Add the secrets

In the GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**

| Name       | Value                          |
|------------|--------------------------------|
| `TG_TOKEN` | the bot token from BotFather   |
| `TG_CHAT`  | your chat id                   |

### 4. Calibrate the detection (recommended first step)

The exact in/out-of-stock wording is the one thing worth verifying. To see what the
checker detects without waiting for an alert:

- Add a **repository variable** (not secret): **Settings → Secrets and variables →
  Actions → Variables tab → New variable** named `DEBUG_NOTIFY` = `1`.
- Go to the **Actions** tab → **stock-check** → **Run workflow**.
- You'll get a Telegram message per product showing `status` and the evidence
  (`cart_button=…, out_markers=…`). Confirm out-of-stock products report
  `out_of_stock` and (when one is available) `in_stock`.
- Once happy, **delete the `DEBUG_NOTIFY` variable** so you only get real alerts.

If the wording differs from what's in `check.py`, tweak `OUT_OF_STOCK_MARKERS` /
`ADD_TO_CART_RE` at the top of [`check.py`](check.py).

## Run it locally (optional)

```bash
pip install -r requirements.txt
python -m playwright install chromium
TG_TOKEN=... TG_CHAT=... DEBUG_NOTIFY=1 python check.py
```

## Notes

- **GitHub disables scheduled workflows after 60 days with no repo commits.** If a
  product stays out of stock for that long, just push any commit (or hit **Run
  workflow** manually) to keep the schedule alive. Most restocks happen well before
  then.
- Cron timing on GitHub's free tier is best-effort and can be delayed several
  minutes at busy times — fine for a 30-minute stock check.
- The schedule is in **UTC**.

[Playwright]: https://playwright.dev/python/
