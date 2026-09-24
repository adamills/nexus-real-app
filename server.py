import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS
from functools import wraps
import requests

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "trading_platform.db"))
app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")
CORS(app, resources={r"/api/*": {"origins": os.getenv("CORS_ORIGINS", "*").split(",")}})

def db():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; return c

def now(): return datetime.now(timezone.utc)
def iso(dt): return dt.astimezone(timezone.utc).isoformat()

def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,wallet_address TEXT,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT,wallet_address TEXT,symbol TEXT NOT NULL,side TEXT NOT NULL,order_type TEXT NOT NULL,quantity REAL NOT NULL,price REAL,leverage INTEGER DEFAULT 1,status TEXT NOT NULL DEFAULT 'ACCEPTED',created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS deposit_wallets(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT NOT NULL,network TEXT NOT NULL,address TEXT NOT NULL,provider_reference TEXT,created_at TEXT NOT NULL,UNIQUE(user_id,network));
        CREATE TABLE IF NOT EXISTS deposits(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT,network TEXT NOT NULL,asset TEXT NOT NULL,amount TEXT NOT NULL,tx_hash TEXT NOT NULL UNIQUE,address TEXT,status TEXT NOT NULL DEFAULT 'pending',confirmations INTEGER DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS strategy_signals(id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT NOT NULL,direction TEXT NOT NULL,timeframe TEXT NOT NULL,note TEXT,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1);
        ''')

def admin_required(fn):
    @wraps(fn)
    def wrapped(*a,**kw):
        token=os.getenv('ADMIN_API_TOKEN'); supplied=request.headers.get('X-Admin-Token') or request.headers.get('Authorization','').removeprefix('Bearer ')
        if token and supplied != token:return jsonify(error='admin authentication required'),401
        if not token and request.remote_addr not in {'127.0.0.1','::1'}:return jsonify(error='set ADMIN_API_TOKEN before exposing admin APIs'),403
        return fn(*a,**kw)
    return wrapped

def page(name, inject=False):
    html=(BASE_DIR/name).read_text(encoding='utf-8')
    if inject:
        script='<script src="/strategy-signals.js" defer></script>'
        html=html.replace('</body>',script+'</body>') if '</body>' in html else html+script
    return Response(html,mimetype='text/html')

@app.get('/')
def home(): return send_from_directory(BASE_DIR,'index.html')
@app.get('/enterprise-mdr')
def mdr(): return page('enterprise-mdr.html',True)
@app.get('/enterprise-mdr-admin')
def admin(): return page('enterprise-mdr-admin.html',True)
@app.get('/enterprise')
def enterprise(): return send_from_directory(BASE_DIR,'enterprise.html')
@app.get('/enterprise-wallet-fixed')
def wallet(): return send_from_directory(BASE_DIR,'enterprise-wallet-fixed.html')
@app.get('/favicon.ico')
def favicon(): return send_from_directory(BASE_DIR,'mdr-icon.png',mimetype='image/png')

@app.get('/api/market')
@app.get('/api/ticker')
def market():
    return jsonify([{'symbol':'BTC','tvSymbol':'BINANCE:BTCUSDT','price':67432.18,'changePct':1.88,'volume':'28.4B'},{'symbol':'ETH','tvSymbol':'BINANCE:ETHUSDT','price':3421.55,'changePct':-1.22,'volume':'14.2B'},{'symbol':'SOL','tvSymbol':'BINANCE:SOLUSDT','price':178.92,'changePct':4.95,'volume':'5.1B'},{'symbol':'BNB','tvSymbol':'BINANCE:BNBUSDT','price':790.89,'changePct':.51,'volume':'9.2B'}])

@app.get('/api/signals')
def signals():
    with db() as c:
        c.execute("UPDATE strategy_signals SET active=0 WHERE active=1 AND expires_at<=?",(iso(now()),))
        rows=c.execute("SELECT id,symbol,direction,timeframe,note,created_at,expires_at FROM strategy_signals WHERE active=1 AND expires_at>? ORDER BY id DESC",(iso(now()),)).fetchall()
    return jsonify([{'id':r['id'],'symbol':r['symbol'],'direction':r['direction'],'timeframe':r['timeframe'],'note':r['note'],'createdAt':r['created_at'],'expiresAt':r['expires_at'],'active':True} for r in rows])

@app.get('/api/admin/signals')
@admin_required
def admin_signals():
    signals();
    with db() as c: rows=c.execute("SELECT * FROM strategy_signals ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify([dict(r,active=bool(r['active'])) for r in rows])

@app.post('/api/admin/signals')
@admin_required
def create_signal():
    p=request.get_json(silent=True) or {}; symbol=str(p.get('symbol','')).upper().strip(); direction=str(p.get('direction','')).upper(); timeframe=str(p.get('timeframe','')).lower(); note=str(p.get('note','')).strip()
    try: minutes=int(p.get('durationMinutes',60))
    except (TypeError,ValueError): return jsonify(error='durationMinutes must be an integer'),400
    if not symbol or direction not in {'LONG','SHORT','WATCH'} or timeframe not in {'15m','1h','4h'} or not 1<=minutes<=10080:return jsonify(error='invalid signal fields'),400
    created=now(); expires=created+timedelta(minutes=minutes)
    with db() as c:
        cur=c.execute("INSERT INTO strategy_signals(symbol,direction,timeframe,note,created_at,expires_at,active) VALUES(?,?,?,?,?,?,1)",(symbol,direction,timeframe,note,iso(created),iso(expires))); sid=cur.lastrowid
    return jsonify(id=sid,symbol=symbol,direction=direction,timeframe=timeframe,note=note,createdAt=iso(created),expiresAt=iso(expires),active=True),201

@app.delete('/api/admin/signals/<int:signal_id>')
@admin_required
def expire_signal(signal_id):
    with db() as c:c.execute('UPDATE strategy_signals SET active=0 WHERE id=?',(signal_id,))
    return jsonify(expired=True)

@app.post('/api/orders')
def create_order():
    p=request.get_json(silent=True) or {}
    try:symbol=str(p['symbol']).upper();side=str(p['side']).upper();typ=str(p.get('type','MARKET')).upper();qty=float(p['quantity']);price=float(p['price']) if p.get('price') not in (None,'') else None;lev=int(p.get('leverage',1))
    except (KeyError,TypeError,ValueError):return jsonify(error='invalid order fields'),400
    if side not in {'BUY','SELL','LONG','SHORT'} or typ not in {'MARKET','LIMIT'} or qty<=0 or not 1<=lev<=125:return jsonify(error='invalid order parameters'),400
    with db() as c: cur=c.execute('INSERT INTO orders(user_id,wallet_address,symbol,side,order_type,quantity,price,leverage,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(p.get('userId'),p.get('walletAddress'),symbol,side,typ,qty,price,lev,'ACCEPTED',iso(now())))
    return jsonify(id=cur.lastrowid,status='ACCEPTED',execution='ledger-only; connect a reviewed execution adapter'),201

@app.get('/api/orders')
def orders():
    with db() as c: rows=c.execute('SELECT * FROM orders ORDER BY id DESC LIMIT 100').fetchall()
    return jsonify([dict(r) for r in rows])

@app.get('/api/portfolio')
def portfolio(): return jsonify(balance=0,positions=[],notice='Connect this endpoint to your custody or exchange ledger.')

@app.get('/api/admin/deposits')
@admin_required
def deposits():
    with db() as c: rows=c.execute('SELECT * FROM deposits ORDER BY id DESC LIMIT 500').fetchall()
    return jsonify([dict(r) for r in rows])

@app.get('/api/admin/wallet-summary')
@admin_required
def summary():
    with db() as c: pending=c.execute("SELECT COUNT(*) FROM deposits WHERE status='pending'").fetchone()[0]; confirmed=c.execute("SELECT COUNT(*) FROM deposits WHERE status='confirmed'").fetchone()[0]
    return jsonify(pendingDeposits=pending,confirmedDeposits=confirmed,evmBalance='server adapter required',tronBalance='server adapter required')

@app.post('/api/admin/deposits/scan')
@admin_required
def scan(): return jsonify(queued=True,message='Configure EVM/TRON scanner workers and verification rules server-side.'),202

@app.post('/api/admin/deposits/webhook')
def webhook():
    if os.getenv('BLOCKCHAIN_WEBHOOK_SECRET') and request.headers.get('X-Webhook-Secret')!=os.getenv('BLOCKCHAIN_WEBHOOK_SECRET'):return jsonify(error='invalid webhook secret'),401
    p=request.get_json(silent=True) or {}; required=['network','asset','amount','txHash']
    if any(not p.get(k) for k in required) or p['network'] not in {'evm','tron'}:return jsonify(error='network, asset, amount and txHash are required'),400
    with db() as c:c.execute('INSERT OR IGNORE INTO deposits(user_id,network,asset,amount,tx_hash,address,status,confirmations,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(p.get('userId'),p['network'],p['asset'],str(p['amount']),p['txHash'],p.get('address'),p.get('status','pending'),int(p.get('confirmations',0)),iso(now()),iso(now())))
    return jsonify(accepted=True),202

if __name__=='__main__':
    init_db(); app.run(host='0.0.0.0',port=int(os.getenv('PORT','5000')),debug=os.getenv('FLASK_DEBUG','0')=='1')
