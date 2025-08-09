
# Automated Futures Trading Project — Full Context & Setup

## 1. Project Purpose
We aim to grow a small trading bankroll quickly while controlling risk, using **automated strategies** so the user only needs to check results in the evenings.  
The main tools are:
- **Pionex** for automated crypto trading (Spot Grid, Futures bots, and custom API trading).
- **eToro** for copy-trading (secondary strategy, more passive).

The user cannot KYC on Binance, but **can KYC elsewhere**. Already has **USDT on Pionex** and a **VPS/PC that can run 24/7**.

---

## 2. History & Decisions

### Phase 1 — Spot Grid Bots
- Started with XRP/USDT and ETH/USDT 7-day grid bots, then added SOL/USDT (30-day) and SHIB/USDT (7-day).
- Observed some profits, but SHIB bot hit stop-loss, and some bots went out of range.
- Conclusion: Grid bots are stable but slow for aggressive growth.

### Phase 2 — Futures Trading
- Decided to move to **Perpetual Futures** for higher potential gains.
- Pionex offers Futures bots and manual trading.
- Default futures bots are too limited — opted for **custom API trading** for flexibility.

---

## 3. Current State (at time of transfer to Cursor)
- **eToro Copy-Trading**: ~$215 value, started with $250. Still running.
- **Pionex**: ~340 USDT in total trading capital.
- Bots running: ETH/USDT grid, XRP/USDT grid, SOL/USDT 30-day grid.
- SHIB bot stopped by stop-loss.
- Decided to shift part of funds into automated futures scalping via custom script.

---

## 4. Target Futures Strategy
- **Pairs**: BTC/USDT, ETH/USDT, SOL/USDT.
- **Mode**: Isolated margin, 3× to 5× leverage.
- **Position size**: ~50 USDT per position.
- **Max open trades**: 2 simultaneously.
- **Entry trigger**: Short-term volatility breakout (price moves ±0.3–0.5% in 1 min).
- **Exit**:
  - Stop-loss = 1.2 × ATR or ~ -2%.
  - Take-profit = 1.5–2 × ATR or ~ +3%.
- **Automation**:
  - Python script calling Pionex API.
  - Runs on local PC or VPS 24/7.
  - Logs trades to CSV.

---

## 5. Technical Setup Instructions

### Create Project Folder & Virtual Environment
```bash
mkdir pionex_futures_bot
cd pionex_futures_bot
python -m venv venv
```

### Activate Virtual Environment
- **Windows (PowerShell)**:
```powershell
.env\Scriptsctivate
```
- **Linux/Mac**:
```bash
source venv/bin/activate
```

### Install Required Packages
```bash
pip install requests websocket-client pandas
```

---

## 6. Pionex API Key Creation
1. Log in to Pionex.
2. Go to **More → API Management**.
3. Create new API Key named `MomentumBot`.
4. Permissions: **Trade + Read**.
5. Copy API Key and API Secret somewhere safe.

---

## 7. Base Script (Single Pair Example)
```python
import requests
import time
import hmac
import hashlib

API_KEY = "YOUR_API_KEY"
API_SECRET = "YOUR_API_SECRET"
BASE_URL = "https://api.pionex.com"

def sign_request(query_string):
    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return signature

def place_order(symbol, side, quantity, leverage=5):
    endpoint = "/api/v1/order"
    params = f"symbol={symbol}&side={side}&type=MARKET&quantity={quantity}&leverage={leverage}&timestamp={int(time.time()*1000)}"
    signature = sign_request(params)
    headers = {"X-MBX-APIKEY": API_KEY}
    url = BASE_URL + endpoint + "?" + params + "&signature=" + signature
    r = requests.post(url, headers=headers)
    print(r.json())

def get_price(symbol):
    r = requests.get(f"{BASE_URL}/api/v1/market/ticker?symbol={symbol}")
    return float(r.json()["price"])

if __name__ == "__main__":
    last_price = get_price("BTCUSDT")
    while True:
        price = get_price("BTCUSDT")
        change = (price - last_price) / last_price * 100
        if change <= -0.3:
            place_order("BTCUSDT", "BUY", 0.001, leverage=5)
        elif change >= 0.3:
            place_order("BTCUSDT", "SELL", 0.001, leverage=5)
        last_price = price
        time.sleep(60)
```

---

## 8. Improvements to Add in Cursor
- Multi-pair support (BTC, ETH, SOL in parallel).
- Dynamic position sizing based on account balance.
- Configurable breakout %, SL, TP.
- Trade logging to CSV.
- Cooldown to prevent rapid-fire entries.

## 9bis. Repository Structure (current)

```
pionex_futures_bot/
  common/
    strategy.py
    state_store.py
    trade_logger.py
  spot/
    bot.py
  perp/
    bot.py
    client.py
  pionex_client.py
  perp_client.py
  config.json
  perp_config.json
  env.example
  requirements.txt
```

---

## 9. Operating Routine
- **Evening**: Check Pionex Futures → Positions → confirm trades closed or active with SL/TP.
- Review CSV logs for performance.
- Weekly: Adjust triggers and SL/TP based on market volatility.
- Withdraw some profits once account grows > 15% from baseline.

---

## 10. Long-Term Roadmap
1. Run small positions for 1–2 weeks to validate.
2. If profitable, scale per-position size to 75–100 USDT.
3. Consider adding alt pairs with high volatility (e.g., DOGE, ADA) for diversification.
4. Automate alerts from TradingView to trigger API calls for even better timing.

---

**End of context — this file contains everything needed to continue the conversation as if it never stopped.**
