import asyncio
import json
import websockets
import statistics
import threading
import time
import os

DERIV_APP_ID = "1089"
SYMBOL = "R_25"

ticks = []
digits = []
times = []

MAX_TICKS = 200

price = 0
signal = "WAIT"
probability = 0
momentum = 0
volatility = 0
tick_speed = 0
liquidity_sweep = "NO"

# -----------------------
# INDICATORS
# -----------------------

def bollinger(data, period=20):
    if len(data) < period:
        return None, None, None
    sma = statistics.mean(data[-period:])
    std = statistics.stdev(data[-period:])
    upper = sma + 2*std
    lower = sma - 2*std
    return upper, sma, lower

def calc_momentum():
    if len(ticks) < 10:
        return 0
    return ticks[-1] - ticks[-10]

def calc_volatility():
    if len(ticks) < 20:
        return 0
    return statistics.stdev(ticks[-20:])

def calc_tick_speed():
    if len(times) < 10:
        return 0
    diff = times[-1] - times[-10]
    if diff == 0:
        return 0
    return round(10 / diff,2)

def detect_sweep():
    global liquidity_sweep
    if len(ticks) < 30:
        return
    high = max(ticks[-30:])
    low = min(ticks[-30:])
    p = ticks[-1]
    if p > high:
        liquidity_sweep = "HIGH SWEEP"
    elif p < low:
        liquidity_sweep = "LOW SWEEP"
    else:
        liquidity_sweep = "NO"

# -----------------------
# SIGNAL ENGINE
# -----------------------

def analyze():
    global momentum, volatility, probability, signal, tick_speed

    upper, mid, lower = bollinger(ticks)
    if upper is None:
        return

    momentum = round(calc_momentum(),4)
    volatility = round(calc_volatility(),4)
    tick_speed = calc_tick_speed()
    detect_sweep()

    prob = 0
    if abs(momentum) > 0.2:
        prob += 30
    if volatility > 0.25:
        prob += 30
    if tick_speed > 3:
        prob += 20
    if liquidity_sweep != "NO":
        prob += 20

    probability = prob

    s = "WAIT"
    p = ticks[-1]

    if prob > 60:
        if p > upper:
            s = "BUY"
        elif p < lower:
            s = "SELL"

    signal = s

    # -----------------------
    # PRINT SIGNALS IN LOGS
    # -----------------------
    print(f"[{time.strftime('%H:%M:%S')}] Price: {p:.3f} | Signal: {signal} | Prob: {prob} | Momentum: {momentum} | Volatility: {volatility} | Tick Speed: {tick_speed} | Sweep: {liquidity_sweep}")

# -----------------------
# STREAM TICKS
# -----------------------

async def stream():
    global price
    url = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
    async with websockets.connect(url) as ws:
        sub = {"ticks": SYMBOL, "subscribe": 1}
        await ws.send(json.dumps(sub))
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            if "tick" in data:
                p = float(data["tick"]["quote"])
                price = p
                ticks.append(p)
                times.append(time.time())
                if len(ticks) > MAX_TICKS:
                    ticks.pop(0)
                    times.pop(0)
                digit = int(str(p)[-1])
                digits.append(digit)
                if len(digits) > 200:
                    digits.pop(0)
                analyze()

def start_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(stream())

# -----------------------
# START
# -----------------------

if __name__ == "__main__":
    print("🚀 Deriv R_25 Signal Bot Starting...")
    t = threading.Thread(target=start_loop)
    t.start()
    t.join()
