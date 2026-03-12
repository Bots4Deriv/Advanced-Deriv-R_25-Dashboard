import asyncio
import json
import statistics
import websockets
import time

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DERIV_APP_ID = "1089"
SYMBOL = "R_25"

ticks = []
price = 0
signal = "NEUTRAL"

auto_trader_running = False
trade_in_progress = False

api_token = ""

trade_history = []
cumulative_profit = 0

max_trades = 0
trade_count = 0

take_profit = 0
stop_loss = 0

stake_amount = 0.35


# -----------------------
# BASIC PAGES
# -----------------------

@app.get("/")
async def home():
    return HTMLResponse("""
    <h2>🚀 Deriv R_25 Trading Bot</h2>
    <p>Bot is running.</p>
    <p>Endpoints:</p>
    <ul>
    <li>/status</li>
    <li>/start</li>
    <li>/stop</li>
    </ul>
    """)


@app.get("/health")
async def health():
    return {"status": "running"}


# -----------------------
# INDICATORS
# -----------------------

def calc_momentum():
    if len(ticks) < 10:
        return 0
    return ticks[-1] - ticks[-10]


def calc_volatility():
    if len(ticks) < 20:
        return 0
    return statistics.stdev(ticks[-20:])


def calc_micro_trend():
    if len(ticks) < 6:
        return "FLAT"

    avg_short = sum(ticks[-3:]) / 3
    avg_long = sum(ticks[-6:]) / 6

    if avg_short > avg_long:
        return "UP"
    elif avg_short < avg_long:
        return "DOWN"
    else:
        return "FLAT"


def analyze_signal():
    global signal

    if len(ticks) < 20:
        signal = "NEUTRAL"
        return

    momentum = calc_momentum()
    volatility = calc_volatility()
    trend = calc_micro_trend()

    if volatility < 0.25:
        signal = "NEUTRAL"
        return

    if momentum > 0 and trend == "UP":
        signal = "BUY"

    elif momentum < 0 and trend == "DOWN":
        signal = "SELL"

    else:
        signal = "NEUTRAL"


# -----------------------
# TICK STREAM
# -----------------------

async def tick_stream():
    global price

    while True:

        try:

            url = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"

            async with websockets.connect(url) as ws:

                await ws.send(json.dumps({
                    "ticks": SYMBOL,
                    "subscribe": 1
                }))

                while True:

                    msg = await ws.recv()
                    data = json.loads(msg)

                    if "tick" in data:
                        price = float(data["tick"]["quote"])
                        ticks.append(price)

                        if len(ticks) > 200:
                            ticks.pop(0)

                        analyze_signal()

        except Exception as e:
            print("Tick stream error:", e)
            await asyncio.sleep(3)


# -----------------------
# TRADE EXECUTION
# -----------------------

async def execute_trade(direction, stake, token):

    global trade_in_progress

    try:

        url = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"

        async with websockets.connect(url) as ws:

            await ws.send(json.dumps({
                "authorize": token
            }))

            await ws.recv()

            contract_type = "PUT" if direction == "BUY" else "CALL"

            proposal = {
                "proposal": 1,
                "amount": round(stake, 2),
                "basis": "stake",
                "contract_type": contract_type,
                "currency": "USD",
                "duration": 15,
                "duration_unit": "s",
                "symbol": SYMBOL
            }

            await ws.send(json.dumps(proposal))

            proposal_response = json.loads(await ws.recv())

            if "error" in proposal_response:
                trade_in_progress = False
                return None, 0

            proposal_id = proposal_response["proposal"]["id"]

            await ws.send(json.dumps({
                "buy": proposal_id,
                "price": round(stake, 2)
            }))

            buy = json.loads(await ws.recv())

            if "error" in buy:
                trade_in_progress = False
                return None, 0

            contract_id = buy["buy"]["contract_id"]

            while True:

                await ws.send(json.dumps({
                    "proposal_open_contract": 1,
                    "contract_id": contract_id
                }))

                result = json.loads(await ws.recv())

                contract = result["proposal_open_contract"]

                if contract["is_sold"]:

                    profit = float(contract["profit"])

                    trade_in_progress = False

                    if profit > 0:
                        return "WIN", profit
                    else:
                        return "LOSS", profit

                await asyncio.sleep(1)

    except Exception as e:
        print("Trade error:", e)
        trade_in_progress = False
        return None, 0


# -----------------------
# AUTO TRADER
# -----------------------

async def auto_trader():

    global auto_trader_running
    global trade_in_progress
    global trade_count
    global cumulative_profit

    while auto_trader_running:

        if take_profit > 0 and cumulative_profit >= take_profit:
            print("TP reached")
            auto_trader_running = False
            break

        if stop_loss > 0 and cumulative_profit <= -abs(stop_loss):
            print("SL reached")
            auto_trader_running = False
            break

        if max_trades > 0 and trade_count >= max_trades:
            print("Max trades reached")
            auto_trader_running = False
            break

        if signal not in ["BUY", "SELL"]:
            await asyncio.sleep(1)
            continue

        if trade_in_progress:
            await asyncio.sleep(1)
            continue

        trade_in_progress = True

        result, profit = await execute_trade(signal, stake_amount, api_token)

        if result is None:
            await asyncio.sleep(2)
            continue

        trade_count += 1
        cumulative_profit += profit

        trade_history.append({
            "timestamp": time.strftime("%H:%M:%S"),
            "direction": signal,
            "profit": profit
        })

        print(f"Trade {trade_count} result:", result, profit)

        await asyncio.sleep(5)


# -----------------------
# STATUS
# -----------------------

@app.get("/status")
async def status():

    return {
        "price": price,
        "signal": signal,
        "profit": cumulative_profit,
        "trades": trade_count,
        "running": auto_trader_running
    }


# -----------------------
# START
# -----------------------

@app.post("/start")
async def start(
    token: str = Form(...),
    stake: float = Form(...),
    max_trades_limit: int = Form(0),
    tp: float = Form(0),
    sl: float = Form(0)
):

    global auto_trader_running
    global api_token
    global stake_amount
    global cumulative_profit
    global trade_count
    global trade_in_progress
    global max_trades
    global take_profit
    global stop_loss

    api_token = token
    stake_amount = round(stake, 2)

    max_trades = max_trades_limit
    take_profit = tp
    stop_loss = sl

    if not auto_trader_running:

        cumulative_profit = 0
        trade_count = 0
        trade_in_progress = False
        trade_history.clear()

        auto_trader_running = True

        asyncio.create_task(auto_trader())

    return {"status": "started"}


# -----------------------
# STOP
# -----------------------

@app.post("/stop")
async def stop():

    global auto_trader_running

    auto_trader_running = False

    return {"status": "stopped"}


# -----------------------
# STARTUP
# -----------------------

@app.on_event("startup")
async def startup():
    asyncio.create_task(tick_stream())
