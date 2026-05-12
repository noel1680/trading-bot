import requests
import pandas as pd
import ta
import time
from concurrent.futures import ThreadPoolExecutor
import os

# CONFIG
MIN_VOLUME = 2_000_000
MIN_PRICE = 0.001
RISK_USDT = 10

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

sent_signals = set()
active_signals = set()

# TELEGRAM
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        print("❌ Error enviando Telegram")

# ✅ SYMBOLS (ARREGLADO)
def get_symbols():

    try:
        data = requests.get("https://api.binance.com/api/v3/ticker/24hr").json()

        # ✅ VALIDAR RESPUESTA
        if isinstance(data, dict):
            print("❌ Binance bloqueado:", data)
            return []

        symbols = []

        for t in data:
            try:
                if float(t['quoteVolume']) >= MIN_VOLUME:
                    if t['symbol'].endswith("USDT"):
                        symbols.append(t['symbol'])
            except:
                continue

        return symbols

    except Exception as e:
        print("❌ Error conexión:", e)
        return []

# ✅ KLINES
def get_klines(symbol):

    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=15m&limit=200"
        data = requests.get(url).json()

        if isinstance(data, dict):
            return None

        return data

    except:
        return None

# ✅ ANALYSIS
def analyze(symbol):

    klines = get_klines(symbol)

    if klines is None:
        return None

    try:
        df = pd.DataFrame(klines, columns=[
            'time','o','h','l','c','v',
            'ct','q','n','tb','tq','ignore'
        ])

        df[['o','h','l','c','v']] = df[['o','h','l','c','v']].astype(float)

        entry = df['c'].iloc[-1]

        if entry < MIN_PRICE:
            return None

        df['ema20'] = ta.trend.ema_indicator(df['c'], 20)
        df['ema50'] = ta.trend.ema_indicator(df['c'], 50)
        df['ema200'] = ta.trend.ema_indicator(df['c'], 200)
        df['rsi'] = ta.momentum.rsi(df['c'], 14)
        df['atr'] = ta.volatility.average_true_range(df['h'], df['l'], df['c'], 14)

        last = df.iloc[-1]
        atr = last['atr']

        if atr == 0 or pd.isna(atr):
            return None

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

        if trend == "LONG":
            sl = entry - 1.5 * atr
            tp1 = entry + atr
            tp2 = entry + 2 * atr
            size = RISK_USDT / (entry - sl)
        else:
            sl = entry + 1.5 * atr
            tp1 = entry - atr
            tp2 = entry - 2 * atr
            size = RISK_USDT / (sl - entry)

        return {
            "symbol": symbol,
            "type": trend,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "score": score
        }

    except:
        return None

# ✅ BOT
def run_bot():

    global active_signals

    print("\n✅ Bot activo")
    print("🚀 NUEVO CICLO\n")

    symbols = get_symbols()

    print(f"📊 Símbolos: {len(symbols)}")

    if len(symbols) == 0:
        print("⚠️ Binance bloqueado → no hay datos")
        return

    signals = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(analyze, symbols[:50])

    for r in results:
        if r:
            signals.append(r)

    if not signals:
        print("❌ No señales\n")
        return

    signals = sorted(signals, key=lambda x: x['score'], reverse=True)

    top = signals[:5]

    print("\n🔥 TOP 5\n")

    for r in top:

        msg = f"""
🔥 {r['type']} {r['symbol']}
📊 Score: {r['score']}
"""

        print(msg)
        send_telegram(msg)

# LOOP
while True:
    run_bot()
    print("⏳ Esperando 60s...\n")
    time.sleep(60)
