import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS
from functools import wraps

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "trading_platform.db"))
app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")
CORS(app, resources={r"/api/*": {"origins": os.getenv("CORS_ORIGINS", "*").split(",")}})

def db():
    c = sqlite3.connect(DB_PATH); c.row_factory = sqlite3.Row; return c

def now(): return datetime.now(timezone.utc)
def iso(dt): return dt.astimezone(timezone.utc).isoformat()

def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT,wallet_address TEXT,symbol TEXT NOT NULL,side TEXT NOT NULL,order_type TEXT NOT NULL,quantity REAL NOT NULL,price REAL,leverage INTEGER DEFAULT 1,status TEXT NOT NULL DEFAULT 'ACCEPTED',created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS strategy_signals(id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT NOT NULL,direction TEXT NOT NULL,timeframe TEXT NOT NULL,note TEXT,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS deposits(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT,network TEXT NOT NULL,asset TEXT NOT NULL,amount TEXT NOT NULL,tx_hash TEXT NOT NULL UNIQUE,address TEXT,status TEXT NOT NULL DEFAULT 'pending',confirmations INTEGER DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        ''')

def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        token = os.getenv('ADMIN_API_TOKEN')
        supplied = request.headers.get('X-Admin-Token') or request.headers.get('Authorization', '').removeprefix('Bearer ')
        if token and supplied != token: return jsonify(error='admin authentication required'), 401
        if not token and request.remote_addr not in {'127.0.0.1', '::1'}: return jsonify(error='set ADMIN_API_TOKEN before exposing admin APIs'), 403
        return fn(*args, **kwargs)
    return wrapped

def page(filename, inject=False):
    html = (BASE_DIR / filename).read_text(encoding='utf-8')
    if inject:
        scripts = '<script src="/strategy-signals.js" defer></script><script src="/realtime-market.js" defer></script>'
        html = html.replace('</body>', scripts + '</body>')
    return Response(html, mimetype='text/html')

@app.get('/')
def home(): return send_from_directory(BASE_DIR, 'index.html')
@app.get('/enterprise-mdr')
def mdr(): return page('enterprise-mdr.html', True)
@app.get('/enterprise-mdr-admin')
def admin(): return page('enterprise-mdr-admin.html', True)
@app.get('/enterprise')
def enterprise(): return send_from_directory(BASE_DIR, 'enterprise.html')
@app.get('/enterprise-wallet-fixed')
def wallet(): return send_from_directory(BASE_DIR, 'enterprise-wallet-fixed.html')
@app.get('/realtime-market.js')
def realtime_js(): return send_from_directory(BASE_DIR, 'realtime-market.js')
@app.get('/strategy-signals.js')
def signals_js(): return send_from_directory(BASE_DIR, 'strategy-signals.js')
@app.get('/favicon.ico')
def favicon(): return send_from_directory(BASE_DIR, 'mdr-icon.png', mimetype='image/png')

@app.get('/api/market')
@app.get('/api/ticker')
def market():
    return jsonify([{'symbol':'BTC','tvSymbol':'BINANCE:BTCUSDT','price':67432.18,'changePct':1.88},{'symbol':'ETH','tvSymbol':'BINANCE:ETHUSDT','price':3421.55,'changePct':-1.22},{'symbol':'SOL','tvSymbol':'BINANCE:SOLUSDT','price':178.92,'changePct':4.95}])

@app.get('/api/signals')
def signals():
    with db() as c:
        c.execute("UPDATE strategy_signals SET active=0 WHERE active=1 AND expires_at<=?", (iso(now()),))
        rows = c.execute("SELECT * FROM strategy_signals WHERE active=1 AND expires_at>? ORDER BY id DESC", (iso(now()),)).fetchall()
    return jsonify([dict(row, active=True) for row in rows])

@app.get('/api/admin/signals')
@admin_required
def admin_signals():
    signals()
    with db() as c: rows = c.execute('SELECT * FROM strategy_signals ORDER BY id DESC LIMIT 100').fetchall()
    return jsonify([dict(row, active=bool(row['active'])) for row in rows])

@app.post('/api/admin/signals')
@admin_required
def create_signal():
    p = request.get_json(silent=True) or {}; symbol = str(p.get('symbol', '')).upper().strip(); direction = str(p.get('direction', '')).upper(); timeframe = str(p.get('timeframe', '')).lower()
    try: minutes = int(p.get('durationMinutes', 60))
    except (TypeError, ValueError): return jsonify(error='durationMinutes must be an integer'), 400
    if not symbol or direction not in {'LONG', 'SHORT', 'WATCH'} or timeframe not in {'15m', '1h', '4h'} or not 1 <= minutes <= 10080: return jsonify(error='invalid signal fields'), 400
    created = now(); expires = created + timedelta(minutes=minutes)
    with db() as c:
        cur = c.execute('INSERT INTO strategy_signals(symbol,direction,timeframe,note,created_at,expires_at,active) VALUES(?,?,?,?,?,?,1)', (symbol, direction, timeframe, str(p.get('note', '')), iso(created), iso(expires)))
    return jsonify(id=cur.lastrowid, symbol=symbol, direction=direction, timeframe=timeframe, expiresAt=iso(expires), active=True), 201

@app.delete('/api/admin/signals/<int:signal_id>')
@admin_required
def expire_signal(signal_id):
    with db() as c: c.execute('UPDATE strategy_signals SET active=0 WHERE id=?', (signal_id,))
    return jsonify(expired=True)

@app.post('/api/orders')
def create_order():
    p = request.get_json(silent=True) or {}
    try:
        symbol = str(p['symbol']).upper(); side = str(p['side']).upper(); order_type = str(p.get('type', 'MARKET')).upper(); quantity = float(p['quantity']); price = float(p['price']) if p.get('price') not in (None, '') else None; leverage = int(p.get('leverage', 1))
    except (KeyError, TypeError, ValueError): return jsonify(error='invalid order fields'), 400
    if side not in {'BUY', 'SELL', 'LONG', 'SHORT'} or order_type not in {'MARKET', 'LIMIT'} or quantity <= 0 or not 1 <= leverage <= 125: return jsonify(error='invalid order parameters'), 400
    with db() as c:
        cur = c.execute('INSERT INTO orders(user_id,wallet_address,symbol,side,order_type,quantity,price,leverage,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)', (p.get('userId'), p.get('walletAddress'), symbol, side, order_type, quantity, price, leverage, 'ACCEPTED', iso(now())))
    return jsonify(id=cur.lastrowid, status='ACCEPTED', execution='ledger-only; connect a reviewed execution adapter'), 201

@app.get('/api/orders')
def orders():
    with db() as c: rows = c.execute('SELECT * FROM orders ORDER BY id DESC LIMIT 100').fetchall()
    return jsonify([dict(row) for row in rows])

if __name__ == '__main__':
    init_db(); app.run(host='0.0.0.0', port=int(os.getenv('PORT', '5000')), debug=os.getenv('FLASK_DEBUG', '0') == '1')
