import json, sqlite3, threading, time, os, datetime, random, hashlib
from collections import defaultdict
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import websocket
from functools import wraps

app = Flask(__name__, static_folder='nexus-real-app')
CORS(app)

DB_FILE = "trading_platform.db"
SYMBOLS = ["btcusdt", "ethusdt", "solusdt", "bnbusdt"]
BINANCE_WS_URL = f"wss://stream.binance.com:9443/ws/{'/'.join([f'{s}@ticker' for s in SYMBOLS])}"

latest_ticks = {}
last_saved = {}

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS market_ticks (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, price REAL, change REAL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
        cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password_hash TEXT, balance REAL DEFAULT 0, demo_balance REAL DEFAULT 10000, role TEXT DEFAULT 'client', status TEXT DEFAULT 'active')")
        cur.execute("CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, type TEXT, amount REAL, currency TEXT DEFAULT 'PKR', gateway TEXT, status TEXT DEFAULT 'pending', proof_image TEXT, custom_data TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        cur.execute("CREATE TABLE IF NOT EXISTS strategies_signals (id INTEGER PRIMARY KEY AUTOINCREMENT, asset_pair TEXT, signal_type TEXT, entry_price REAL, target_price REAL, success_rate REAL DEFAULT 75, status TEXT DEFAULT 'active')")
        cur.execute("CREATE TABLE IF NOT EXISTS custom_fields (id INTEGER PRIMARY KEY AUTOINCREMENT, module TEXT, field_name TEXT, field_type TEXT, is_required INTEGER DEFAULT 1, options TEXT)")

        cur.execute("SELECT id FROM users WHERE email='admin@mdrtradex.com'")
        if not cur.fetchone():
            cur.execute("INSERT INTO users (email,password_hash,balance,role) VALUES (?,?,?,?)", ('admin@mdrtradex.com', hashlib.sha256('admin123'.encode()).hexdigest(), 100000, 'admin'))
            cur.execute("INSERT INTO users (email,password_hash,balance,role) VALUES (?,?,?,?)", ('client@test.com', hashlib.sha256('123456'.encode()).hexdigest(), 5000, 'client'))
            cur.execute("INSERT INTO custom_fields (module,field_name,field_type,is_required,options) VALUES (?,?,?,?,?)", ('deposit','Payment Gateway','select',1, json.dumps(["JazzCash","Easypaisa","Bank Card","Crypto USDT TRC20"])))
            cur.execute("INSERT INTO custom_fields (module,field_name,field_type,is_required) VALUES (?,?,?,?)", ('deposit','JazzCash / Easypaisa Number','text',1))
            cur.execute("INSERT INTO custom_fields (module,field_name,field_type,is_required) VALUES (?,?,?,?)", ('deposit','TRC20 Wallet Reference Hash','text',1))
            cur.execute("INSERT INTO custom_fields (module,field_name,field_type,is_required) VALUES (?,?,?,?)", ('deposit','Proof Screenshot','file',1))
        conn.commit()

# WebSocket Binance Feed Thread
def on_ws_message(ws, message):
    try:
        data = json.loads(message)
        sym = data.get('s', '').lower()
        price = float(data.get('c', 0))
        change = float(data.get('P', 0))
        if sym:
            latest_ticks[sym] = {'price': price, 'change': change, 'time': time.time()}
            now = time.time()
            if sym not in last_saved or now - last_saved[sym] > 2:
                last_saved[sym] = now
                with get_db() as conn:
                    conn.execute("INSERT INTO market_ticks (symbol, price, change) VALUES (?, ?, ?)", (sym, price, change))
                    conn.commit()
    except Exception:
        pass

def start_ws():
    while True:
        try:
            ws = websocket.WebSocketApp(BINANCE_WS_URL, on_message=on_ws_message)
            ws.run_forever(ping_interval=20)
        except Exception:
            time.sleep(5)

# API Routes
@app.route('/')
def serve_client():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/ticker')
def get_ticker():
    res = []
    for s in SYMBOLS:
        t = latest_ticks.get(s, {'price': 0, 'change': 0})
        res.append({'symbol': s.upper(), 'price': t['price'], 'change': t['change']})
    return jsonify(res)

@app.route('/api/history/<symbol>')
def get_history(symbol):
    sym = symbol.lower()
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT price, timestamp FROM market_ticks WHERE symbol=? ORDER BY id DESC LIMIT 40", (sym,))
        rows = cur.fetchall()

    if not rows:
        base_price = 80444.0 if sym == 'btcusdt' else (2450.0 if sym == 'ethusdt' else 145.2)
        candles = []
        p = base_price
        for _ in range(30):
            open_p = p
            close_p = open_p + (random.random() - 0.48) * (p * 0.003)
            high_p = max(open_p, close_p) + random.random() * (p * 0.001)
            low_p = min(open_p, close_p) - random.random() * (p * 0.001)
            candles.append({'open': round(open_p, 2), 'close': round(close_p, 2), 'high': round(high_p, 2), 'low': round(low_p, 2)})
            p = close_p
        return jsonify(candles)

    rows.reverse()
    candles = []
    for r in rows:
        p = r['price']
        candles.append({'open': round(p - 2, 2), 'close': round(p, 2), 'high': round(p + 3, 2), 'low': round(p - 4, 2)})
    return jsonify(candles)

@app.route('/api/custom-fields')
def get_custom_fields():
    mod = request.args.get('module', 'deposit')
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT field_name, field_type, is_required, options FROM custom_fields WHERE module=?", (mod,))
        rows = cur.fetchall()

    fields = []
    for r in rows:
        opts = r['options']
        if opts and isinstance(opts, str):
            try:
                opts = json.loads(opts)
            except ValueError:
                pass
        fields.append({
            'field_name': r['field_name'],
            'field_type': r['field_type'],
            'is_required': bool(r['is_required']),
            'options': opts
        })
    return jsonify({'data': fields})

@app.route('/api/transactions/request', methods=['POST'])
def handle_tx_request():
    data = request.json or {}
    user_id = data.get('user_id', 2)
    tx_type = data.get('type', 'deposit')
    amount = float(data.get('amount', 0))
    gateway = data.get('gateway', 'JazzCash')

    if amount <= 0:
        return jsonify({'status': 'error', 'message': 'Invalid transaction amount'}), 400

    with get_db() as conn:
        cur = conn.cursor()
        if tx_type == 'withdrawal':
            cur.execute("SELECT balance FROM users WHERE id=?", (user_id,))
            user = cur.fetchone()
            if not user or user['balance'] < amount:
                return jsonify({'status': 'error', 'message': 'Insufficient account balance'}), 400

        cur.execute(
            "INSERT INTO transactions (user_id, type, amount, gateway, custom_data) VALUES (?, ?, ?, ?, ?)",
            (user_id, tx_type, amount, gateway, json.dumps(data))
        )
        conn.commit()

    return jsonify({'status': 'success', 'message': f'{tx_type.capitalize()} request of ${amount} via {gateway} submitted!'})

if __name__ == '__main__':
    init_db()
    threading.Thread(target=start_ws, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
