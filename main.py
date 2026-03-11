import asyncio
import json
import websockets
import statistics
import os
import threading
import time
from flask import Flask, render_template_string

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

signals = []

app = Flask(__name__)

# -----------------------
# INDICATORS
# -----------------------

def bollinger(data, period=20):

    if len(data) < period:
        return None,None,None

    sma = statistics.mean(data[-period:])
    std = statistics.stdev(data[-period:])

    upper = sma + 2*std
    lower = sma - 2*std

    return upper,sma,lower


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


# -----------------------
# LIQUIDITY SWEEP
# -----------------------

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
# DIGIT ANALYSIS
# -----------------------

def digit_stats():

    counts = {i:0 for i in range(10)}

    for d in digits[-50:]:
        counts[d]+=1

    return counts


# -----------------------
# SIGNAL ENGINE
# -----------------------

def analyze():

    global momentum,volatility,probability,signal,tick_speed

    upper,mid,lower = bollinger(ticks)

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

    if s != "WAIT":

        signals.append({
            "signal":s,
            "price":p
        })

        if len(signals) > 10:
            signals.pop(0)


# -----------------------
# STREAM TICKS
# -----------------------

async def stream():

    global price

    url = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"

    async with websockets.connect(url) as ws:

        sub = {"ticks":SYMBOL,"subscribe":1}

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
# DASHBOARD
# -----------------------

HTML = """

<h1>Deriv Advanced Synthetic Dashboard</h1>

<h2>Symbol: R_25</h2>

<h2>Price: {{price}}</h2>

<h2>Signal: {{signal}}</h2>

<h3>Large Move Probability: {{prob}} %</h3>

<ul>
<li>Momentum: {{momentum}}</li>
<li>Volatility: {{volatility}}</li>
<li>Tick Speed: {{speed}} ticks/sec</li>
<li>Liquidity Sweep: {{sweep}}</li>
</ul>

<h3>Digit Frequency</h3>

<table border=1>
<tr>
{% for d in digits %}
<th>{{d}}</th>
{% endfor %}
</tr>

<tr>
{% for v in digits.values() %}
<td>{{v}}</td>
{% endfor %}
</tr>
</table>

<h3>Recent Signals</h3>

<table border=1>
<tr>
<th>Signal</th>
<th>Price</th>
</tr>

{% for s in signals %}

<tr>
<td>{{s.signal}}</td>
<td>{{s.price}}</td>
</tr>

{% endfor %}

</table>

"""

@app.route("/")

def dashboard():

    return render_template_string(
        HTML,
        price=price,
        signal=signal,
        prob=probability,
        momentum=momentum,
        volatility=volatility,
        speed=tick_speed,
        sweep=liquidity_sweep,
        digits=digit_stats(),
        signals=signals
    )


# -----------------------
# START
# -----------------------

if __name__ == "__main__":

    t = threading.Thread(target=start_loop)
    t.start()

    port = int(os.environ.get("PORT",8080))

    app.run(host="0.0.0.0",port=port)
