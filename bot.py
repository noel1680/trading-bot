from binance.client import Client
import pandas as pd
import ta
import requests
import time
from concurrent.futures import ThreadPoolExecutor
import os

# ================= CONFIG =================
client = Client()  # ✅ Binance real

MIN_VOLUME = 2_000_000
MIN_PRICE = 0.001
RISK_USDT = 10

TOKEN = "TU_TOKEN"
CHAT_ID = "TU_CHAT_ID"

sent_signals = set()
active_signals = set()

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
    tickers = client.get_ticker()

    symbols = []

    for t in tickers:
        try:
            symbol = t['symbol']
            volume = float(t['quoteVolume'])

            if symbol.endswith('USDT') and volume >= MIN_VOLUME:
                symbols.append(symbol)

        except:
            continue

    return symbols

# ================= SCORE =================
def calculate_score(df):

    last = df.iloc[-1]
    score = 0

    # ✅ tendencia fuerte
    if last['ema20'] > last['ema50'] > last['ema200']:
        score += 30
    elif last['ema20'] < last['ema50'] < last['ema200']:
        score += 30

    # ✅ RSI saludable
    if 50 < last['rsi'] < 70:
        score += 20

    # ✅ volumen fuerte
    vol_avg = df['v'].rolling(20).mean().iloc[-1]
    if last['v'] > vol_avg:
        score += 20

    # ✅ momentum
    if df['c'].iloc[-1] > df['c'].iloc[-5]:
        score += 30

    return score

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

        entry = df['c'].iloc[-1]

        # ✅ FILTRO PRECIO
        if entry < MIN_PRICE:
            return None

        # indicadores
        df['ema20'] = ta.trend.ema_indicator(df['c'], 20)
        df['ema50'] = ta.trend.ema_indicator(df['c'], 50)
        df['ema200'] = ta.trend.ema_indicator(df['c'], 200)
        df['rsi'] = ta.momentum.rsi(df['c'], 14)
        df['atr'] = ta.volatility.average_true_range(df['h'], df['l'], df['c'], 14)

        last = df.iloc[-1]
        atr = last['atr']

        if atr == 0 or pd.isna(atr):
            return None

        score = calculate_score(df)

        if score < 60:
            return None

        # ✅ LONG
        if last['ema20'] > last['ema50'] > last['ema200']:

            sl = entry - 1.5 * atr
            risk = entry - sl
            if risk <= 0:
                return None

            size = RISK_USDT / risk
            tp1 = entry + atr
            tp2 = entry + 2 * atr
            trade_type = "LONG"

        # ✅ SHORT
        elif last['ema20'] < last['ema50'] < last['ema200']:

            sl = entry + 1.5 * atr
            risk = sl - entry
            if risk <= 0:
                return None

            size = RISK_USDT / risk
            tp1 = entry - atr
            tp2 = entry - 2 * atr
            trade_type = "SHORT"

        else:
            return None

        return {
            "symbol": symbol,
            "type": trade_type,
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

    print("\n✅ Bot activo")
    print("🚀 NUEVO CICLO\n")

    symbols = get_symbols()
    print(f"📊 Símbolos encontrados: {len(symbols)}")

    signals = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(analyze, symbols[:50])

    for r in results:
        if r:
            signals.append(r)

    if len(signals) == 0:
        print("❌ No se encontraron señales\n")
        return

    # ✅ ordenar por score
    signals = sorted(signals, key=lambda x: x['score'], reverse=True)

    top_signals = signals[:5]
    new_active = set()

    print("\n🔥 TOP 5 SEÑALES\n")

    for r in top_signals:

        key = f"{r['symbol']}_{r['type']}"
        new_active.add(key)

        if key not in sent_signals:

            sent_signals.add(key)

            msg = f"""
🔥 {r['type']} {r['symbol']}

Entry: {r['entry']:.6f}
SL: {r['sl']:.6f}

TP1: {r['tp1']:.6f}
TP2: {r['tp2']:.6f}

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

Esta señal ya no es válida.
"""

        print(msg)
        send_telegram(msg)

    active_signals = new_active

# ================= LOOP =================
try:
    while True:
        run_bot()
        print("\n⏳ Esperando 60 segundos...\n")
        time.sleep(60)

except KeyboardInterrupt:
    print("\n🛑 Bot detenido")
