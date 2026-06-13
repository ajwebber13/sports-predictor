import yfinance as yf
import pandas as pd
import requests
from datetime import datetime
import os

# --- CONFIG ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

WATCHLIST = {
    "NVDA": "NVIDIA Corp",
    "AMD": "Advanced Micro Devices",
    "META": "Meta Platforms",
    "GOOGL": "Alphabet",
    "MSFT": "Microsoft",
    "AAPL": "Apple",
    "JPM": "JPMorgan Chase",
    "BAC": "Bank of America",
    "V": "Visa",
    "MA": "Mastercard",
    "SOFI": "SoFi Technologies",
    "XOM": "Exxon Mobil",
    "CVX": "Chevron",
    "NEE": "NextEra Energy",
    "AMZN": "Amazon",
    "NKE": "Nike",
    "SBUX": "Starbucks",
    "TSLA": "Tesla",
    "COIN": "Coinbase",
    "PLTR": "Palantir",
    "MS": "Morgan Stanley",
    "GS": "Goldman Sachs",
}

# --- SIGNAL LOGIC ---
def get_signal(ticker):
    try:
        df = yf.download(ticker, period="60d", interval="1d", progress=False, auto_adjust=True)
        if df.empty or len(df) < 20:
            return None

        close = df["Close"].squeeze()
        volume = df["Volume"].squeeze()

        # RSI (14-period)
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -delta.clip(upper=0).rolling(14).mean()
        rs = gain / loss
        rsi = (100 - (100 / (1 + rs))).iloc[-1]

        # MACD
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd = ema12 - ema26
        signal_line = macd.ewm(span=9).mean()
        macd_cross = (macd.iloc[-1] > signal_line.iloc[-1]) and (macd.iloc[-2] <= signal_line.iloc[-2])

        # Volume spike (vs 20-day avg)
        avg_volume = volume.iloc[-21:-1].mean()
        vol_ratio = volume.iloc[-1] / avg_volume if avg_volume > 0 else 1.0

        current_price = float(close.iloc[-1])

        # Score signals
        signals = []
        direction = None

        if rsi < 30:
            signals.append(f"RSI oversold ({rsi:.0f})")
            direction = "BUY"
        elif rsi > 70:
            signals.append(f"RSI overbought ({rsi:.0f})")
            direction = "SELL"

        if macd_cross:
            signals.append("MACD crossover")
            if direction is None:
                direction = "BUY"

        if vol_ratio >= 2.0:
            signals.append(f"volume {vol_ratio:.1f}x avg")

        if not signals or direction is None:
            return None

        # Star rating
        stars = len(signals)
        if stars >= 3:
            star_str = "★★★"
        elif stars == 2:
            star_str = "★★"
        else:
            star_str = "★"

        # Target / stop (simple %)
        if direction == "BUY":
            target = round(current_price * 1.05, 2)
            arrow = "▲"
        else:
            target = round(current_price * 0.95, 2)
            arrow = "▼"

        pct = round(((target - current_price) / current_price) * 100, 1)

        # Options flag: high vol ratio or stars >= 2
        options_flag = vol_ratio >= 1.8 and stars >= 2

        return {
            "ticker": ticker,
            "name": WATCHLIST[ticker],
            "direction": direction,
            "arrow": arrow,
            "stars": star_str,
            "price": current_price,
            "target": target,
            "pct": pct,
            "why": " + ".join(signals),
            "options": options_flag,
        }

    except Exception as e:
        print(f"Error on {ticker}: {e}")
        return None


# --- ALERT FORMAT ---
def format_alert(signal):
    date_str = datetime.now().strftime("%B %d, %Y")
    options_line = "Options play: Yes" if signal["options"] else ""

    lines = [
        "CULTURE & PULSE PICKS",
        f"Stock Signal · {date_str}",
        "",
        f"${signal['ticker']} · {signal['name']}",
        f"Signal: {signal['direction']} {signal['arrow']} | {signal['stars']}",
        f"Price: ${signal['price']:.2f} → Target ${signal['target']:.2f} ({signal['pct']:+.1f}%)",
        f"Why: {signal['why']}",
    ]

    if options_line:
        lines.append(options_line)

    return "\n".join(lines)


# --- TELEGRAM ---
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }
    r = requests.post(url, json=payload)
    return r.status_code == 200


# --- MAIN ---
def run_scan():
    print(f"Running scan — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    results = []

    for ticker in WATCHLIST:
        signal = get_signal(ticker)
        if signal:
            results.append(signal)
            print(f"  Signal: {ticker} {signal['direction']} {signal['stars']}")
        else:
            print(f"  No signal: {ticker}")

    # Sort: ★★★ first, then BUY before SELL
    results.sort(key=lambda x: (x["stars"] != "★★★", x["direction"] != "BUY"))

    if not results:
        print("No signals today.")
        return

    for signal in results:
        msg = format_alert(signal)
        print(f"\n--- ALERT ---\n{msg}\n")
        sent = send_telegram(msg)
        print(f"Telegram: {'sent' if sent else 'FAILED'}")


if __name__ == "__main__":
    run_scan()
