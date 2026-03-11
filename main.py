import asyncio
import json
import statistics
import websockets
import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

DERIV_APP_ID = "1089"
SYMBOL = "R_25"

ticks=[]
times=[]

price=0
signal="NEUTRAL"
market="UNKNOWN"

rsi=50
momentum=0
volatility=0
ma9=0
ma21=0
confidence=0
tick_speed=0
sweep="NONE"

# -----------------------
# INDICATORS
# -----------------------

def MA(period):
    if len(ticks)<period:
        return None
    return sum(ticks[-period:])/period


def MOMENTUM():
    if len(ticks)<10:
        return 0
    return ticks[-1]-ticks[-10]


def VOL():
    if len(ticks)<20:
        return 0
    return statistics.stdev(ticks[-20:])


def RSI(period=14):

    if len(ticks)<period+1:
        return 50

    gains=[]
    losses=[]

    for i in range(-period,-1):

        diff=ticks[i+1]-ticks[i]

        if diff>0:
            gains.append(diff)
        else:
            losses.append(abs(diff))

    avg_gain=sum(gains)/period if gains else 0.0001
    avg_loss=sum(losses)/period if losses else 0.0001

    rs=avg_gain/avg_loss

    return 100-(100/(1+rs))

# -----------------------
# MARKET STRUCTURE
# -----------------------

def market_structure():

    global market

    if len(ticks)<30:
        return

    range_size=max(ticks[-20:]) - min(ticks[-20:])

    if range_size < 0.2:
        market="CONSOLIDATION"

    elif abs(momentum)>0.5:
        market="BREAKOUT"

    elif ma9>ma21:
        market="UPTREND"

    elif ma9<ma21:
        market="DOWNTREND"

    else:
        market="RANGE"

# -----------------------
# SIGNAL ENGINE
# -----------------------

def analyze():

    global signal,rsi,momentum,volatility,ma9,ma21,confidence

    if len(ticks)<30:
        return

    ma9=MA(9)
    ma21=MA(21)

    momentum=MOMENTUM()
    volatility=VOL()
    rsi=RSI()

    market_structure()

    score=0

    if ma9>ma21:
        score+=25
    else:
        score-=25

    if rsi>55:
        score+=25
    elif rsi<45:
        score-=25

    if momentum>0:
        score+=25
    else:
        score-=25

    if abs(volatility)>=0.4:
        score+=25

    confidence=abs(score)

    if score>=50:
        signal="BUY"
    elif score<=-50:
        signal="SELL"
    else:
        signal="NEUTRAL"

# -----------------------
# DERIV STREAM
# -----------------------

async def stream():

    global price

    url=f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"

    async with websockets.connect(url) as ws:

        await ws.send(json.dumps({
            "ticks":SYMBOL,
            "subscribe":1
        }))

        while True:

            msg=await ws.recv()
            data=json.loads(msg)

            if "tick" in data:

                p=float(data["tick"]["quote"])
                price=p

                ticks.append(p)
                times.append(time.time())

                if len(ticks)>200:
                    ticks.pop(0)
                    times.pop(0)

                analyze()

# -----------------------
# WEB DASHBOARD
# -----------------------

@app.get("/", response_class=HTMLResponse)
async def home():

    return f"""
    <html>
    <head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>

    body {{
        background:black;
        color:white;
        text-align:center;
        font-family:Arial;
    }}

    .circle {{
        width:300px;
        height:300px;
        border-radius:50%;
        background:{'green' if signal=='BUY' else 'red' if signal=='SELL' else 'gray'};
        display:flex;
        align-items:center;
        justify-content:center;
        flex-direction:column;
        margin:auto;
        margin-top:80px;
        font-size:28px;
    }}

    </style>
    </head>

    <body>

    <div class="circle">
    {price:.3f}<br>{signal}<br>{confidence}%
    </div>

    <h3>Market: {market}</h3>
    <p>RSI: {round(rsi,1)} | Volatility: {round(volatility,3)}</p>

    <script>
    setTimeout(()=>location.reload(),1000)
    </script>

    </body>
    </html>
    """

# -----------------------
# START STREAM
# -----------------------

@app.on_event("startup")
async def start():

    asyncio.create_task(stream())
