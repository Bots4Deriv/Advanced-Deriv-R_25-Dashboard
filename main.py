import asyncio
import json
import websockets
import statistics
import time
import threading
from dataclasses import dataclass, asdict
from datetime import datetime
from collections import deque, Counter
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
import socket

# Configuration
DERIV_APP_ID = "1089"
SYMBOL = "R_25"
MAX_TICKS = 200
MAX_DIGITS = 500  # Keep more digit history

# Global state for dashboard
class SignalState:
    def __init__(self):
        self.ticks = deque(maxlen=MAX_TICKS)
        self.digits = deque(maxlen=MAX_DIGITS)
        self.times = deque(maxlen=MAX_TICKS)
        self.signals = deque(maxlen=100)  # Signal history
        
        # Current values
        self.price = 0.0
        self.current_digit = 0
        self.signal = "WAIT"
        self.probability = 0
        self.momentum = 0.0
        self.volatility = 0.0
        self.tick_speed = 0.0
        self.liquidity_sweep = "NO"
        self.bb_upper = 0.0
        self.bb_middle = 0.0
        self.bb_lower = 0.0
        
        # Digit analysis
        self.digit_stats = {i: 0 for i in range(10)}  # Frequency count
        self.digit_percentages = {i: 0 for i in range(10)}
        self.last_digits = []  # Last 20 digits for display
        self.digit_trend = "NEUTRAL"  # Rising, Falling, Neutral
        self.even_odd_ratio = "50/50"
        self.over_under_5 = "50/50"
        self.consecutive_digits = 1  # How many times same digit appeared
        self.digit_momentum = 0  # Average of last 5 digits
        
        # Stats
        self.total_signals = 0
        self.buy_signals = 0
        self.sell_signals = 0
        self.start_time = time.time()
        
    def update_digit_analysis(self):
        if len(self.digits) < 10:
            return
            
        # Frequency analysis
        digit_list = list(self.digits)
        counter = Counter(digit_list)
        total = len(digit_list)
        
        for i in range(10):
            self.digit_stats[i] = counter.get(i, 0)
            self.digit_percentages[i] = round((counter.get(i, 0) / total) * 100, 1)
        
        # Last 20 digits for display
        self.last_digits = digit_list[-20:] if len(digit_list) >= 20 else digit_list
        
        # Even/Odd analysis
        even_count = sum(1 for d in digit_list if d % 2 == 0)
        odd_count = total - even_count
        self.even_odd_ratio = f"{round((even_count/total)*100)}%/{round((odd_count/total)*100)}%"
        
        # Over/Under 5
        over_count = sum(1 for d in digit_list if d > 5)
        under_count = sum(1 for d in digit_list if d < 5)
        five_count = sum(1 for d in digit_list if d == 5)
        self.over_under_5 = f"Over:{round((over_count/total)*100)}% | Under:{round((under_count/total)*100)}% | 5:{round((five_count/total)*100)}%"
        
        # Consecutive detection
        if len(digit_list) >= 2:
            current = digit_list[-1]
            consecutive = 1
            for d in reversed(digit_list[:-1]):
                if d == current:
                    consecutive += 1
                else:
                    break
            self.consecutive_digits = consecutive
        
        # Digit momentum (average of last 5)
        self.digit_momentum = round(statistics.mean(digit_list[-5:]), 2) if len(digit_list) >= 5 else 0
        
        # Trend analysis (last 10 vs previous 10)
        if len(digit_list) >= 20:
            recent = statistics.mean(digit_list[-10:])
            previous = statistics.mean(digit_list[-20:-10])
            if recent > previous + 0.5:
                self.digit_trend = "RISING 📈"
            elif recent < previous - 0.5:
                self.digit_trend = "FALLING 📉"
            else:
                self.digit_trend = "NEUTRAL ➡️"
        
    def to_dict(self):
        return {
            "price": self.price,
            "current_digit": self.current_digit,
            "signal": self.signal,
            "probability": self.probability,
            "momentum": self.momentum,
            "volatility": self.volatility,
            "tick_speed": self.tick_speed,
            "liquidity_sweep": self.liquidity_sweep,
            "bb_upper": self.bb_upper,
            "bb_middle": self.bb_middle,
            "bb_lower": self.bb_lower,
            "ticks": list(self.ticks),
            "signals": list(self.signals),
            "uptime": int(time.time() - self.start_time),
            "total_signals": self.total_signals,
            "buy_count": self.buy_signals,
            "sell_count": self.sell_signals,
            "symbol": SYMBOL,
            # Digit data
            "digit_stats": self.digit_stats,
            "digit_percentages": self.digit_percentages,
            "last_digits": self.last_digits,
            "digit_trend": self.digit_trend,
            "even_odd_ratio": self.even_odd_ratio,
            "over_under_5": self.over_under_5,
            "consecutive_digits": self.consecutive_digits,
            "digit_momentum": self.digit_momentum
        }

state = SignalState()

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
    if len(state.ticks) < 10:
        return 0
    return state.ticks[-1] - state.ticks[-10]

def calc_volatility():
    if len(state.ticks) < 20:
        return 0
    return statistics.stdev(list(state.ticks)[-20:])

def calc_tick_speed():
    if len(state.times) < 10:
        return 0
    diff = state.times[-1] - state.times[-10]
    if diff == 0:
        return 0
    return round(10 / diff, 2)

def detect_sweep():
    if len(state.ticks) < 30:
        state.liquidity_sweep = "NO"
        return
    recent = list(state.ticks)[-30:]
    high = max(recent)
    low = min(recent)
    p = state.ticks[-1]
    if p > high:
        state.liquidity_sweep = "HIGH SWEEP"
    elif p < low:
        state.liquidity_sweep = "LOW SWEEP"
    else:
        state.liquidity_sweep = "NO"

# -----------------------
# SIGNAL ENGINE
# -----------------------

def analyze():
    upper, mid, lower = bollinger(list(state.ticks))
    if upper is None:
        return
    
    state.bb_upper = round(upper, 3)
    state.bb_middle = round(mid, 3)
    state.bb_lower = round(lower, 3)
    state.momentum = round(calc_momentum(), 4)
    state.volatility = round(calc_volatility(), 4)
    state.tick_speed = calc_tick_speed()
    detect_sweep()
    
    # Update digit analysis
    state.update_digit_analysis()
    
    # Enhanced probability with digit analysis
    prob = 0
    if abs(state.momentum) > 0.2:
        prob += 25
    if state.volatility > 0.25:
        prob += 25
    if state.tick_speed > 3:
        prob += 15
    if state.liquidity_sweep != "NO":
        prob += 15
    
    # Digit-based probability boost
    if state.consecutive_digits >= 3:
        prob += 10  # Unusual pattern
    if state.digit_momentum > 7 or state.digit_momentum < 3:
        prob += 10  # Extreme digit momentum
    
    state.probability = min(100, prob)
    
    prev_signal = state.signal
    p = state.ticks[-1]
    state.price = round(p, 3)
    
    new_signal = "WAIT"
    if prob > 60:
        if p > upper:
            new_signal = "SELL"
        elif p < lower:
            new_signal = "BUY"
    
    state.signal = new_signal
    
    # Track signal changes
    if new_signal != "WAIT" and new_signal != prev_signal:
        state.total_signals += 1
        if new_signal == "BUY":
            state.buy_signals += 1
        else:
            state.sell_signals += 1
        
        signal_record = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "signal": new_signal,
            "price": state.price,
            "digit": state.current_digit,
            "prob": prob,
            "momentum": state.momentum
        }
        state.signals.append(signal_record)

# -----------------------
# WEBSOCKET STREAM
# -----------------------

async def stream():
    url = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
    while True:
        try:
            async with websockets.connect(url) as ws:
                print("✅ Connected to Deriv")
                sub = {"ticks": SYMBOL, "subscribe": 1}
                await ws.send(json.dumps(sub))
                
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    if "tick" in data:
                        p = float(data["tick"]["quote"])
                        state.ticks.append(p)
                        state.times.append(time.time())
                        
                        # Extract digit
                        digit = int(str(p)[-1])
                        state.current_digit = digit
                        state.digits.append(digit)
                        
                        analyze()
        except Exception as e:
            print(f"⚠️ Connection error: {e}")
            await asyncio.sleep(3)

def start_stream():
    asyncio.run(stream())

# -----------------------
# HTTP SERVER & DASHBOARD
# -----------------------

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/data':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(state.to_dict()).encode())
        elif self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML_DASHBOARD.encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass

def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port

def start_server():
    port = find_free_port()
    server = HTTPServer(('localhost', port), DashboardHandler)
    print(f"\n🌐 Dashboard running at: http://localhost:{port}")
    webbrowser.open(f'http://localhost:{port}')
    server.serve_forever()

# -----------------------
# HTML DASHBOARD
# -----------------------

HTML_DASHBOARD = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Deriv R_25 Signal Dashboard with Digit Analysis</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
            color: #fff;
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1600px;
            margin: 0 auto;
        }
        
        header {
            text-align: center;
            margin-bottom: 30px;
            padding: 20px;
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
        }
        
        h1 {
            font-size: 2.5em;
            background: linear-gradient(90deg, #00d2ff, #3a7bd5);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 10px;
        }
        
        .subtitle {
            color: #888;
            font-size: 0.9em;
        }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .card {
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            padding: 20px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
            transition: transform 0.3s;
        }
        
        .card:hover {
            transform: translateY(-5px);
        }
        
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        
        .card-title {
            font-size: 0.9em;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .card-value {
            font-size: 2em;
            font-weight: bold;
        }
        
        .signal-buy {
            color: #00ff88;
            text-shadow: 0 0 20px rgba(0,255,136,0.5);
        }
        
        .signal-sell {
            color: #ff4757;
            text-shadow: 0 0 20px rgba(255,71,87,0.5);
        }
        
        .signal-wait {
            color: #ffa502;
        }
        
        .price-up {
            color: #00ff88;
        }
        
        .price-down {
            color: #ff4757;
        }
        
        .indicator-bar {
            width: 100%;
            height: 8px;
            background: rgba(255,255,255,0.1);
            border-radius: 4px;
            margin-top: 10px;
            overflow: hidden;
        }
        
        .indicator-fill {
            height: 100%;
            border-radius: 4px;
            transition: width 0.5s ease;
        }
        
        .probability-high { background: linear-gradient(90deg, #00ff88, #00d2ff); }
        .probability-med { background: linear-gradient(90deg, #ffa502, #ff6348); }
        .probability-low { background: linear-gradient(90deg, #ff4757, #ff6348); }
        
        .chart-container {
            position: relative;
            height: 300px;
            margin-top: 20px;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin-top: 15px;
        }
        
        .stat-box {
            text-align: center;
            padding: 15px;
            background: rgba(255,255,255,0.03);
            border-radius: 10px;
        }
        
        .stat-label {
            font-size: 0.8em;
            color: #666;
            margin-bottom: 5px;
        }
        
        .stat-value {
            font-size: 1.3em;
            font-weight: bold;
            color: #fff;
        }
        
        .sweep-indicator {
            display: inline-block;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: bold;
        }
        
        .sweep-high {
            background: rgba(255,71,87,0.3);
            color: #ff4757;
            border: 1px solid #ff4757;
        }
        
        .sweep-low {
            background: rgba(0,255,136,0.3);
            color: #00ff88;
            border: 1px solid #00ff88;
        }
        
        .sweep-none {
            background: rgba(255,255,255,0.1);
            color: #888;
        }
        
        .signal-history {
            max-height: 300px;
            overflow-y: auto;
        }
        
        .signal-item {
            display: flex;
            justify-content: space-between;
            padding: 10px;
            margin-bottom: 8px;
            background: rgba(255,255,255,0.03);
            border-radius: 8px;
            border-left: 3px solid transparent;
        }
        
        .signal-item.buy {
            border-left-color: #00ff88;
        }
        
        .signal-item.sell {
            border-left-color: #ff4757;
        }
        
        .pulse {
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .live-indicator {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: #00ff88;
            font-size: 0.9em;
        }
        
        .live-dot {
            width: 8px;
            height: 8px;
            background: #00ff88;
            border-radius: 50%;
            animation: blink 1s infinite;
        }
        
        @keyframes blink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }
        
        .bb-levels {
            display: flex;
            justify-content: space-between;
            margin-top: 10px;
            font-size: 0.8em;
            color: #888;
        }
        
        .connection-status {
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 10px 20px;
            border-radius: 20px;
            font-size: 0.9em;
            backdrop-filter: blur(10px);
        }
        
        .connected {
            background: rgba(0,255,136,0.2);
            color: #00ff88;
            border: 1px solid #00ff88;
        }
        
        .disconnected {
            background: rgba(255,71,87,0.2);
            color: #ff4757;
            border: 1px solid #ff4757;
        }
        
        /* Digit specific styles */
        .digit-display {
            font-size: 3em;
            font-weight: bold;
            text-align: center;
            padding: 20px;
            border-radius: 15px;
            background: rgba(255,255,255,0.05);
            margin-bottom: 15px;
            transition: all 0.3s;
        }
        
        .digit-high { color: #ff4757; text-shadow: 0 0 30px rgba(255,71,87,0.6); }
        .digit-mid { color: #ffa502; text-shadow: 0 0 30px rgba(255,165,2,0.6); }
        .digit-low { color: #00ff88; text-shadow: 0 0 30px rgba(0,255,136,0.6); }
        
        .digit-flow {
            display: flex;
            gap: 8px;
            justify-content: center;
            flex-wrap: wrap;
            margin-top: 15px;
        }
        
        .digit-box {
            width: 35px;
            height: 35px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 8px;
            font-weight: bold;
            font-size: 1.1em;
            transition: all 0.3s;
        }
        
        .digit-box.high { background: rgba(255,71,87,0.3); color: #ff4757; border: 1px solid #ff4757; }
        .digit-box.mid { background: rgba(255,165,2,0.3); color: #ffa502; border: 1px solid #ffa502; }
        .digit-box.low { background: rgba(0,255,136,0.3); color: #00ff88; border: 1px solid #00ff88; }
        
        .digit-stats-grid {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 8px;
            margin-top: 15px;
        }
        
        .digit-stat {
            text-align: center;
            padding: 8px;
            background: rgba(255,255,255,0.03);
            border-radius: 6px;
            font-size: 0.85em;
        }
        
        .digit-stat-value {
            font-size: 1.3em;
            font-weight: bold;
            margin-bottom: 2px;
        }
        
        .digit-stat-label {
            font-size: 0.75em;
            color: #666;
        }
        
        .trend-up { color: #00ff88; }
        .trend-down { color: #ff4757; }
        .trend-neutral { color: #ffa502; }
        
        .consecutive-alert {
            background: rgba(255,71,87,0.2);
            border: 1px solid #ff4757;
            color: #ff4757;
            padding: 8px 15px;
            border-radius: 20px;
            font-size: 0.9em;
            font-weight: bold;
            text-align: center;
            margin-top: 10px;
        }
        
        .two-col {
            grid-column: span 2;
        }
        
        @media (max-width: 768px) {
            .two-col { grid-column: span 1; }
        }
    </style>
</head>
<body>
    <div class="connection-status connected" id="connStatus">● Live</div>
    
    <div class="container">
        <header>
            <h1>🔮 Deriv R_25 Signal Bot</h1>
            <div class="subtitle">
                <span class="live-indicator">
                    <span class="live-dot"></span>
                    Real-time Market & Digit Analysis
                </span>
                | Uptime: <span id="uptime">0s</span>
            </div>
        </header>
        
        <div class="grid">
            <!-- Current Price -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Current Price</span>
                    <span id="priceArrow">→</span>
                </div>
                <div class="card-value" id="currentPrice">0.000</div>
                <div class="indicator-bar">
                    <div class="indicator-fill probability-high" id="priceBar" style="width: 50%"></div>
                </div>
            </div>
            
            <!-- Current Digit -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Current Digit</span>
                    <span id="digitTrend">➡️</span>
                </div>
                <div class="digit-display digit-mid" id="currentDigit">0</div>
                <div style="display: flex; justify-content: space-between; font-size: 0.85em; color: #888;">
                    <span>Consecutive: <strong id="consecutiveCount" style="color: #fff;">1</strong></span>
                    <span>Momentum: <strong id="digitMomentum" style="color: #fff;">0.00</strong></span>
                </div>
                <div id="consecutiveAlert" style="display: none;" class="consecutive-alert">
                    ⚠️ Consecutive Pattern Detected!
                </div>
            </div>
            
            <!-- Signal -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Signal</span>
                    <span id="signalIcon">⏸</span>
                </div>
                <div class="card-value signal-wait" id="signalText">WAIT</div>
                <div class="stats-grid">
                    <div class="stat-box">
                        <div class="stat-label">BUY</div>
                        <div class="stat-value" id="buyCount" style="color: #00ff88">0</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">SELL</div>
                        <div class="stat-value" id="sellCount" style="color: #ff4757">0</div>
                    </div>
                </div>
            </div>
            
            <!-- Probability -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Signal Strength</span>
                    <span id="probPercent">0%</span>
                </div>
                <div class="card-value" id="probability">0%</div>
                <div class="indicator-bar">
                    <div class="indicator-fill probability-low" id="probBar" style="width: 0%"></div>
                </div>
            </div>
        </div>
        
        <div class="grid">
            <!-- Digit Flow -->
            <div class="card two-col">
                <div class="card-header">
                    <span class="card-title">Last 20 Digits Flow</span>
                    <span style="font-size: 0.8em; color: #666;">Newest →</span>
                </div>
                <div class="digit-flow" id="digitFlow">
                    <!-- Filled by JS -->
                </div>
                <div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid rgba(255,255,255,0.1);">
                    <div style="display: flex; justify-content: space-between; font-size: 0.9em; color: #888; margin-bottom: 8px;">
                        <span>Even/Odd Ratio:</span>
                        <strong id="evenOddRatio" style="color: #fff;">50/50</strong>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 0.9em; color: #888;">
                        <span>Over/Under 5:</span>
                        <strong id="overUnder5" style="color: #fff;">50/50</strong>
                    </div>
                </div>
            </div>
            
            <!-- Digit Statistics -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Digit Frequency (%)</span>
                    <span style="font-size: 0.8em; color: #666;">Distribution</span>
                </div>
                <div class="digit-stats-grid" id="digitStats">
                    <!-- Filled by JS -->
                </div>
            </div>
        </div>
        
        <div class="grid">
            <!-- Indicators -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Technical Indicators</span>
                </div>
                
                <div style="margin-bottom: 15px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                        <span style="color: #888; font-size: 0.9em;">Momentum</span>
                        <span id="momentum" style="font-weight: bold;">0.0000</span>
                    </div>
                    <div class="indicator-bar">
                        <div class="indicator-fill" id="momBar" style="width: 50%; background: #3a7bd5;"></div>
                    </div>
                </div>
                
                <div style="margin-bottom: 15px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                        <span style="color: #888; font-size: 0.9em;">Volatility</span>
                        <span id="volatility" style="font-weight: bold;">0.0000</span>
                    </div>
                    <div class="indicator-bar">
                        <div class="indicator-fill" id="volBar" style="width: 0%; background: #ffa502;"></div>
                    </div>
                </div>
                
                <div style="margin-bottom: 15px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                        <span style="color: #888; font-size: 0.9em;">Tick Speed</span>
                        <span id="tickSpeed" style="font-weight: bold;">0.00 ticks/s</span>
                    </div>
                    <div class="indicator-bar">
                        <div class="indicator-fill" id="speedBar" style="width: 0%; background: #00d2ff;"></div>
                    </div>
                </div>
                
                <div style="text-align: center; margin-top: 20px;">
                    <span class="sweep-indicator sweep-none" id="sweepIndicator">NO SWEEP</span>
                </div>
            </div>
            
            <!-- Bollinger Bands -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Bollinger Bands (20)</span>
                </div>
                <div class="chart-container" style="height: 200px;">
                    <canvas id="bbChart"></canvas>
                </div>
                <div class="bb-levels">
                    <span>Lower: <span id="bbLower">0.000</span></span>
                    <span>Mid: <span id="bbMid">0.000</span></span>
                    <span>Upper: <span id="bbUpper">0.000</span></span>
                </div>
            </div>
            
            <!-- Signal History -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Recent Signals</span>
                    <span style="font-size: 0.8em; color: #666;">Last 20</span>
                </div>
                <div class="signal-history" id="signalHistory">
                    <div style="text-align: center; color: #666; padding: 20px;">
                        Waiting for signals...
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Price Chart -->
        <div class="card">
            <div class="card-header">
                <span class="card-title">Price Chart (Last 200 Ticks)</span>
                <span style="font-size: 0.8em; color: #666;" id="tickCount">0 ticks</span>
            </div>
            <div class="chart-container">
                <canvas id="priceChart"></canvas>
            </div>
        </div>
        
        <!-- Digit Distribution Chart -->
        <div class="card">
            <div class="card-header">
                <span class="card-title">Digit Distribution Analysis</span>
                <span style="font-size: 0.8em; color: #666;">Frequency & Patterns</span>
            </div>
            <div class="chart-container">
                <canvas id="digitChart"></canvas>
            </div>
        </div>
    </div>

    <script>
        let priceChart, bbChart, digitChart;
        let lastPrice = 0;
        
        // Initialize charts
        function initCharts() {
            // Price chart
            const ctx = document.getElementById('priceChart').getContext('2d');
            priceChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Price',
                        data: [],
                        borderColor: '#00d2ff',
                        backgroundColor: 'rgba(0,210,255,0.1)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.4,
                        pointRadius: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { display: false },
                        y: {
                            grid: { color: 'rgba(255,255,255,0.1)' },
                            ticks: { color: '#888' }
                        }
                    },
                    animation: false
                }
            });
            
            // BB chart
            const bbCtx = document.getElementById('bbChart').getContext('2d');
            bbChart = new Chart(bbCtx, {
                type: 'bar',
                data: {
                    labels: ['Upper', 'Middle', 'Lower'],
                    datasets: [{
                        data: [0, 0, 0],
                        backgroundColor: [
                            'rgba(255,71,87,0.6)',
                            'rgba(255,255,255,0.3)',
                            'rgba(0,255,136,0.6)'
                        ],
                        borderColor: ['#ff4757', '#fff', '#00ff88'],
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: {
                            grid: { color: 'rgba(255,255,255,0.1)' },
                            ticks: { color: '#888' }
                        },
                        x: { ticks: { color: '#888' } }
                    }
                }
            });
            
            // Digit distribution chart
            const digitCtx = document.getElementById('digitChart').getContext('2d');
            digitChart = new Chart(digitCtx, {
                type: 'bar',
                data: {
                    labels: ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'],
                    datasets: [{
                        label: 'Frequency %',
                        data: [0,0,0,0,0,0,0,0,0,0],
                        backgroundColor: [
                            'rgba(0,255,136,0.6)', 'rgba(0,255,136,0.5)', 
                            'rgba(0,255,136,0.4)', 'rgba(255,165,2,0.4)',
                            'rgba(255,165,2,0.5)', 'rgba(255,165,2,0.6)',
                            'rgba(255,165,2,0.5)', 'rgba(255,165,2,0.4)',
                            'rgba(255,71,87,0.4)', 'rgba(255,71,87,0.6)'
                        ],
                        borderColor: [
                            '#00ff88', '#00ff88', '#00d2ff', '#ffa502',
                            '#ffa502', '#ffa502', '#ffa502', '#ff6348',
                            '#ff4757', '#ff4757'
                        ],
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { 
                        legend: { display: false },
                        annotation: {
                            annotations: {
                                line5: {
                                    type: 'line',
                                    xMin: 4.5,
                                    xMax: 4.5,
                                    borderColor: 'rgba(255,255,255,0.3)',
                                    borderWidth: 2,
                                    borderDash: [5, 5]
                                }
                            }
                        }
                    },
                    scales: {
                        y: {
                            grid: { color: 'rgba(255,255,255,0.1)' },
                            ticks: { color: '#888' },
                            max: 20
                        },
                        x: { ticks: { color: '#888' } }
                    }
                }
            });
        }
        
        function getDigitClass(d) {
            if (d >= 0 && d <= 3) return 'low';
            if (d >= 4 && d <= 6) return 'mid';
            return 'high';
        }
        
        function getDigitDisplayClass(d) {
            if (d >= 0 && d <= 3) return 'digit-low';
            if (d >= 4 && d <= 6) return 'digit-mid';
            return 'digit-high';
        }
        
        function updateDashboard(data) {
            // Update price
            const priceEl = document.getElementById('currentPrice');
            const prevPrice = parseFloat(priceEl.textContent);
            priceEl.textContent = data.price.toFixed(3);
            
            if (data.price > prevPrice) {
                priceEl.className = 'card-value price-up';
                document.getElementById('priceArrow').textContent = '↑';
            } else if (data.price < prevPrice) {
                priceEl.className = 'card-value price-down';
                document.getElementById('priceArrow').textContent = '↓';
            }
            
            // Update current digit
            const digitEl = document.getElementById('currentDigit');
            digitEl.textContent = data.current_digit;
            digitEl.className = 'digit-display ' + getDigitDisplayClass(data.current_digit);
            
            // Update digit trend
            const trendEl = document.getElementById('digitTrend');
            trendEl.textContent = data.digit_trend;
            if (data.digit_trend.includes('RISING')) trendEl.className = 'trend-up';
            else if (data.digit_trend.includes('FALLING')) trendEl.className = 'trend-down';
            else trendEl.className = 'trend-neutral';
            
            // Update consecutive
            document.getElementById('consecutiveCount').textContent = data.consecutive_digits;
            document.getElementById('digitMomentum').textContent = data.digit_momentum;
            
            const alertEl = document.getElementById('consecutiveAlert');
            if (data.consecutive_digits >= 3) {
                alertEl.style.display = 'block';
                alertEl.textContent = `⚠️ ${data.consecutive_digits}x Consecutive ${data.current_digit}s!`;
            } else {
                alertEl.style.display = 'none';
            }
            
            // Update digit flow
            const flowEl = document.getElementById('digitFlow');
            flowEl.innerHTML = data.last_digits.map(d => 
                `<div class="digit-box ${getDigitClass(d)}">${d}</div>`
            ).join('');
            
            // Update ratios
            document.getElementById('evenOddRatio').textContent = data.even_odd_ratio;
            document.getElementById('overUnder5').textContent = data.over_under_5;
            
            // Update digit stats grid
            const statsEl = document.getElementById('digitStats');
            statsEl.innerHTML = Object.entries(data.digit_percentages).map(([digit, pct]) => `
                <div class="digit-stat">
                    <div class="digit-stat-value" style="color: ${getDigitColor(parseInt(digit))}">${pct}%</div>
                    <div class="digit-stat-label">Digit ${digit}</div>
                </div>
            `).join('');
            
            // Update signal
            const signalEl = document.getElementById('signalText');
            const signalIcon = document.getElementById('signalIcon');
            signalEl.textContent = data.signal;
            
            if (data.signal === 'BUY') {
                signalEl.className = 'card-value signal-buy pulse';
                signalIcon.textContent = '🟢';
            } else if (data.signal === 'SELL') {
                signalEl.className = 'card-value signal-sell pulse';
                signalIcon.textContent = '🔴';
            } else {
                signalEl.className = 'card-value signal-wait';
                signalIcon.textContent = '⏸';
            }
            
            // Update probability
            document.getElementById('probability').textContent = data.probability + '%';
            document.getElementById('probPercent').textContent = data.probability + '%';
            const probBar = document.getElementById('probBar');
            probBar.style.width = data.probability + '%';
            
            if (data.probability > 60) probBar.className = 'indicator-fill probability-high';
            else if (data.probability > 30) probBar.className = 'indicator-fill probability-med';
            else probBar.className = 'indicator-fill probability-low';
            
            // Update indicators
            document.getElementById('momentum').textContent = data.momentum.toFixed(4);
            document.getElementById('volatility').textContent = data.volatility.toFixed(4);
            document.getElementById('tickSpeed').textContent = data.tick_speed.toFixed(2) + ' ticks/s';
            
            const momPct = Math.min(100, Math.max(0, 50 + (data.momentum * 100)));
            document.getElementById('momBar').style.width = momPct + '%';
            
            const volPct = Math.min(100, (data.volatility / 0.5) * 100);
            document.getElementById('volBar').style.width = volPct + '%';
            
            const speedPct = Math.min(100, (data.tick_speed / 5) * 100);
            document.getElementById('speedBar').style.width = speedPct + '%';
            
            // Update sweep
            const sweepEl = document.getElementById('sweepIndicator');
            sweepEl.textContent = data.liquidity_sweep;
            if (data.liquidity_sweep === 'HIGH SWEEP') sweepEl.className = 'sweep-indicator sweep-high';
            else if (data.liquidity_sweep === 'LOW SWEEP') sweepEl.className = 'sweep-indicator sweep-low';
            else sweepEl.className = 'sweep-indicator sweep-none';
            
            // Update Bollinger
            document.getElementById('bbUpper').textContent = data.bb_upper.toFixed(3);
            document.getElementById('bbMid').textContent = data.bb_middle.toFixed(3);
            document.getElementById('bbLower').textContent = data.bb_lower.toFixed(3);
            
            bbChart.data.datasets[0].data = [data.bb_upper, data.bb_middle, data.bb_lower];
            bbChart.update('none');
            
            // Update stats
            document.getElementById('buyCount').textContent = data.buy_count;
            document.getElementById('sellCount').textContent = data.sell_count;
            document.getElementById('uptime').textContent = data.uptime + 's';
            document.getElementById('tickCount').textContent = data.ticks.length + ' ticks';
            
            // Update price chart
            const labels = data.ticks.map((_, i) => i);
            priceChart.data.labels = labels;
            priceChart.data.datasets[0].data = data.ticks;
            priceChart.update('none');
            
            // Update digit chart
            digitChart.data.datasets[0].data = Object.values(data.digit_percentages);
            digitChart.update('none');
            
            // Update signal history
            const historyEl = document.getElementById('signalHistory');
            if (data.signals.length > 0) {
                historyEl.innerHTML = data.signals.slice().reverse().map(s => `
                    <div class="signal-item ${s.signal.toLowerCase()}">
                        <div>
                            <strong style="color: ${s.signal === 'BUY' ? '#00ff88' : '#ff4757'}">${s.signal}</strong>
                            <div style="font-size: 0.8em; color: #666;">${s.time} | Digit: ${s.digit}</div>
                        </div>
                        <div style="text-align: right;">
                            <div>${s.price.toFixed(3)}</div>
                            <div style="font-size: 0.8em; color: #666;">${s.prob}% prob</div>
                        </div>
                    </div>
                `).join('');
            }
        }
        
        function getDigitColor(d) {
            if (d >= 0 && d <= 3) return '#00ff88';
            if (d >= 4 && d <= 6) return '#ffa502';
            return '#ff4757';
        }
        
        async function fetchData() {
            try {
                const response = await fetch('/api/data');
                const data = await response.json();
                updateDashboard(data);
                document.getElementById('connStatus').className = 'connection-status connected';
                document.getElementById('connStatus').textContent = '● Live';
            } catch (e) {
                document.getElementById('connStatus').className = 'connection-status disconnected';
                document.getElementById('connStatus').textContent = '● Offline';
            }
        }
        
        // Init
        initCharts();
        fetchData();
        setInterval(fetchData, 1000);
    </script>
</body>
</html>
"""

# -----------------------
# MAIN
# -----------------------

if __name__ == "__main__":
    # Start WebSocket stream in background
    ws_thread = threading.Thread(target=start_stream, daemon=True)
    ws_thread.start()
    
    # Start web server
    start_server()
