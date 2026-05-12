from binance.client import Client
import pandas as pd
import ta
import requests
import time
from concurrent.futures import ThreadPoolExecutor

# ================= CONFIG =================
client = Client()

MIN_VOLUME = 2_000_000
MIN_PRICE = 0.001
RISK_USDT = 10

import os
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

sent_signals = set()
active_signals = set()

# ================= TELEGRAM =================
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

# ================= SYMBOLS =================
def get_symbols():

    tickers = client.get_ticker()

    symbols = []

    for t in tickers:
        symbol = t['symbol']
        volume = float(t['quoteVolume'])

        if symbol.endswith('USDT') and volume >= MIN_VOLUME:
            symbols.append(symbol)

    return symbols

# ================= ANALYSIS =================
def analyze(symbol):

    try:
        klines = client.get_klines(
            symbol=symbol,
            interval='15m',
            limit=200
        )

        df = pd.DataFrame(klines, columns=[
            'time','o','h','l','c','v',
            'ct','q','n','tb','tq','ignore'
        ])

        df[['o','h','l','c','v']] = df[['o','h','l','c','v']].astype(float)

        df['ema20'] = ta.trend.ema_indicator(df['c'], 20)
        df['ema50'] = ta.trend.ema_indicator(df['c'], 50)
        df['ema200'] = ta.trend.ema_indicator(df['c'], 200)
        df['rsi'] = ta.momentum.rsi(df['c'], 14)
        df['atr'] = ta.volatility.average_true_range(df['h'], df['l'], df['c'], 14)

        last = df.iloc[-1]

        entry = last['c']
        atr = last['atr']

        # ✅ filtro precio
        if entry < MIN_PRICE or atr == 0:
            return None

        # ✅ score REAL
        score = 0

        if last['ema20'] > last['ema50'] > last['ema200']:
            score += 30
            trend = "LONG"
        elif last['ema20'] < last['ema50'] < last['ema200']:
            score += 30
            trend = "SHORT"
        else:
            return None

        if 50 < last['rsi'] < 70:
            score += 20

        vol_avg = df['v'].rolling(20).mean().iloc[-1]
        if last['v'] > vol_avg:
            score += 20

        if df['c'].iloc[-1] > df['c'].iloc[-5]:
            score += 30

        if score < 60:
            return None

        # ✅ LONG
        if trend == "LONG":
            sl = entry - 1.5 * atr
            size = RISK_USDT / (entry - sl)
            tp1 = entry + atr
            tp2 = entry + 2 * atr

        # ✅ SHORT
        else:
            sl = entry + 1.5 * atr
            size = RISK_USDT / (sl - entry)
            tp1 = entry - atr
            tp2 = entry - 2 * atr

        return {
            "symbol": symbol,
            "type": trend,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "size": size,
            "score": score
        }

    except:
        return None

# ================= BOT =================
def run_bot():

    global active_signals

    print("\n🚀 NUEVO CICLO\n")

    symbols = get_symbols()
    print(f"Símbolos: {len(symbols)}")

    signals = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(analyze, symbols[:50])

    for r in results:
        if r:
            signals.append(r)

    if not signals:
        print("❌ No señales\n")
        return

    # ✅ ordenar por score
    signals = sorted(signals, key=lambda x: x['score'], reverse=True)

    top_signals = signals[:5]

    new_active = set()

    print("\n✅ TOP 5\n")

    for r in top_signals:

        key = f"{r['symbol']}_{r['type']}"
        new_active.add(key)

        if key not in sent_signals:

            sent_signals.add(key)

            msg = f"""
🔥 {r['type']} {r['symbol']}

Entry: {r['entry']:.4f}
SL: {r['sl']:.4f}

TP1: {r['tp1']:.4f}
TP2: {r['tp2']:.4f}

📊 Score: {r['score']}
"""

            print(msg)
            send_telegram(msg)

    # ✅ INVALIDADOS
    invalidated = active_signals - new_active

    for key in invalidated:
        symbol, side = key.split("_")

        msg = f"""
⚠️ INVALIDADO

{side} {symbol}
"""
        send_telegram(msg)

    active_signals = new_active

# ================= LOOP =================
try:
    while True:
        print("✅ Bot activo")
        run_bot()
        print("⏳ Esperando 60s...\n")
        time.sleep(60)

except KeyboardInterrupt:
    print("\n🛑 Bot detenido")
