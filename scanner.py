from pybit.unified_trading import HTTP
import pandas as pd
import ta
import requests
import time
import csv
import os
import random
from concurrent.futures import ThreadPoolExecutor

# ================= CONFIG =================
session = HTTP(testnet=False)

MIN_VOLUME = 2_000_000
MIN_PRICE = 0.001   # 🔥 NUEVO FILTRO
RISK_USDT = 10
MIN_PROFIT_FACTOR = 1.3

import os

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

sent_signals = set()
active_signals = set()

# ================= FILES =================
if not os.path.exists("signals.csv"):
    with open("signals.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp","symbol","type","entry","sl","tp1","tp2","score"])

if not os.path.exists("trades.csv"):
    with open("trades.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp","symbol","type","entry","sl","tp1","tp2","result","profit"])

# ================= TELEGRAM =================
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
        print("📲 Telegram enviado")
    except Exception as e:
        print("❌ Error Telegram:", e)

# ================= SYMBOLS =================
def get_symbols():
    try:
        data = session.get_tickers(category="linear")
        return [
            t['symbol']
            for t in data['result']['list']
            if t['symbol'].endswith("USDT")
            and float(t['turnover24h']) >= MIN_VOLUME
        ]
    except:
        return []

# ================= BACKTEST =================
def backtest_symbol(symbol):
    try:
        data = session.get_kline(category="linear", symbol=symbol, interval="15", limit=200)

        df = pd.DataFrame(data['result']['list'], columns=[
            'time','open','high','low','close','volume','turnover'
        ])

        df[['open','high','low','close']] = df[['open','high','low','close']].astype(float)
        df = df.iloc[::-1]

        df['ema20'] = ta.trend.ema_indicator(df['close'], 20)
        df['ema50'] = ta.trend.ema_indicator(df['close'], 50)

        wins, losses = 0, 0

        for i in range(50, len(df)-10):
            row = df.iloc[i]
            if row['ema20'] > row['ema50']:
                wins += 1
            else:
                losses += 1

        if wins + losses == 0:
            return None

        pf = (wins / losses) if losses > 0 else 2
        return {"profit_factor": pf}

    except:
        return None

# ================= SCORE =================
def calculate_score(df):

    last = df.iloc[-1]
    score = 0

    if last['ema20'] > last['ema50'] > last['ema200']:
        score += 30
    elif last['ema20'] < last['ema50'] < last['ema200']:
        score += 30

    if 50 < last['rsi'] < 70:
        score += 20

    vol_avg = df['volume'].rolling(20).mean().iloc[-1]
    if df['volume'].iloc[-1] > vol_avg:
        score += 20

    if df['close'].iloc[-1] > df['close'].iloc[-5]:
        score += 30

    return score

# ================= ANALYSIS =================
def analyze(symbol):

    try:
        data = session.get_kline(category="linear", symbol=symbol, interval="15", limit=200)

        df = pd.DataFrame(data['result']['list'], columns=[
            'time','open','high','low','close','volume','turnover'
        ])

        df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].astype(float)
        df = df.iloc[::-1]

        last_price = df['close'].iloc[-1]

        # ✅ NUEVO FILTRO PRECIO
        if last_price < MIN_PRICE:
            return None

        df['ema20'] = ta.trend.ema_indicator(df['close'], 20)
        df['ema50'] = ta.trend.ema_indicator(df['close'], 50)
        df['ema200'] = ta.trend.ema_indicator(df['close'], 200)
        df['rsi'] = ta.momentum.rsi(df['close'], 14)
        df['atr'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], 14)

        last = df.iloc[-1]

        entry = last['close']
        atr = last['atr']

        if pd.isna(atr):
            return None

        trend_long = last['ema20'] > last['ema50'] > last['ema200']
        trend_short = last['ema20'] < last['ema50'] < last['ema200']

        score = calculate_score(df)

        if score < 50:
            return None

        if trend_long:
            sl = entry - 1.5 * atr
            size = RISK_USDT / (entry - sl)
            return {
                "type":"LONG","symbol":symbol,"entry":entry,
                "sl":sl,"tp1":entry+atr,"tp2":entry+2*atr,
                "size":size,"score":score
            }

        if trend_short:
            sl = entry + 1.5 * atr
            size = RISK_USDT / (sl - entry)
            return {
                "type":"SHORT","symbol":symbol,"entry":entry,
                "sl":sl,"tp1":entry-atr,"tp2":entry-2*atr,
                "size":size,"score":score
            }

    except:
        return None

# ================= BOT =================
def run_bot():

    global active_signals

    print("\n🚀 NUEVO CICLO\n")

    symbols = get_symbols()
    print(f"Símbolos: {len(symbols)}")

    valid_symbols = []

    for s in symbols[:20]:
        bt = backtest_symbol(s)
        if bt and bt['profit_factor'] > MIN_PROFIT_FACTOR:
            valid_symbols.append(s)

    print(f"✅ Validados: {len(valid_symbols)}")

    signals = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = executor.map(analyze, valid_symbols)

    for r in results:
        if r:
            signals.append(r)

    if not signals:
        print("❌ No señales")
        return

    # ✅ ORDENAR POR SCORE
    signals = sorted(signals, key=lambda x: x['score'], reverse=True)

    top_signals = signals[:5]

    new_active = set()

    print("\n✅ TOP 5 SEÑALES\n")

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

    # ✅ INVALIDACIONES
    invalidated = active_signals - new_active

    for key in invalidated:

        symbol, side = key.split("_")

        msg = f"""
⚠️ INVALIDADO

{side} {symbol}

Esta señal dejó de ser válida.
"""

        print(msg)
        send_telegram(msg)

    active_signals = new_active

# ================= LOOP =================


try:
    while True:

        from datetime import datetime

        print(f"✅ Bot activo - {datetime.now()}")

        run_bot()

        print("⏳ Esperando 60s...\n")
        time.sleep(60)

except KeyboardInterrupt:
    print("\n🛑 Bot detenido")
