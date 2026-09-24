import os
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "trading_platform.db"))
SOLSCAN_BASE_URL = os.getenv("SOLSCAN_BASE_URL", "https://pro-api.solscan.io/v2.0").rstrip("/")
app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")
CORS(app, resources={r"/api/*": {"origins": os.getenv("CORS_ORIGINS", "*").split(",")}})


def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def now():
    return datetime.now(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat()


def init_db():
    with db() as connection:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, wallet_address TEXT, symbol TEXT NOT NULL, side TEXT NOT NULL, order_type TEXT NOT NULL, quantity REAL NOT NULL, price REAL, leverage INTEGER DEFAULT 1, status TEXT NOT NULL DEFAULT 'ACCEPTED', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS strategy_signals (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, direction TEXT NOT NULL, timeframe TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS deposits (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, network TEXT NOT NULL, asset TEXT NOT NULL, amount TEXT NOT NULL, tx_hash TEXT NOT NULL UNIQUE, address TEXT, status TEXT NOT NULL DEFAULT 'pending', confirmations INTEGER DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS deposit_wallets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, network TEXT NOT NULL, address TEXT NOT NULL, provider_reference TEXT, created_at TEXT NOT NULL, UNIQUE(user_id, network));
        """)


def admin_required(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        configured = os.getenv("ADMIN_API_TOKEN")
        supplied = request.headers.get("X-Admin-Token") or request.headers.get("Authorization", "").removeprefix("Bearer ")
        if configured and supplied != configured:
            return jsonify(error="admin authentication required"), 401
        if not configured and request.remote_addr not in {"127.0.0.1", "::1"}:
            return jsonify(error="set ADMIN_API_TOKEN before exposing admin APIs"), 403
        return function(*args, **kwargs)
    return wrapped


def page(filename, inject=False):
    html = (BASE_DIR / filename).read_text(encoding="utf-8")
    if inject:
        html = html.replace("</body>", '<script src="/strategy-signals.js" defer></script><script src="/realtime-market.js" defer></script></body>')
    return Response(html, mimetype="text/html")


@app.get("/")
def home(): return send_from_directory(BASE_DIR, "index.html")

@app.get("/enterprise")
def enterprise(): return send_from_directory(BASE_DIR, "enterprise.html")

@app.get("/enterprise-mdr")
def enterprise_mdr(): return page("enterprise-mdr.html", True)

@app.get("/enterprise-mdr-admin")
@app.get("/admin-panel")
@app.get("/admin")
def enterprise_mdr_admin(): return page("enterprise-mdr-admin.html", True)

@app.get("/enterprise-wallet-fixed")
def wallet(): return send_from_directory(BASE_DIR, "enterprise-wallet-fixed.html")

@app.get("/realtime-market.js")
def realtime_market(): return send_from_directory(BASE_DIR, "realtime-market.js")

@app.get("/strategy-signals.js")
def strategy_signals(): return send_from_directory(BASE_DIR, "strategy-signals.js")

@app.get("/favicon.ico")
def favicon(): return send_from_directory(BASE_DIR, "mdr-icon.png", mimetype="image/png")


@app.get("/api/market")
@app.get("/api/ticker")
def market():
    return jsonify([
        {"symbol": "BTC", "tvSymbol": "BINANCE:BTCUSDT", "price": 67432.18, "changePct": 1.88},
        {"symbol": "ETH", "tvSymbol": "BINANCE:ETHUSDT", "price": 3421.55, "changePct": -1.22},
        {"symbol": "SOL", "tvSymbol": "BINANCE:SOLUSDT", "price": 178.92, "changePct": 4.95},
    ])


@app.get("/api/signals")
def signals():
    current = iso(now())
    with db() as connection:
        connection.execute("UPDATE strategy_signals SET active=0 WHERE active=1 AND expires_at<=?", (current,))
        rows = connection.execute("SELECT * FROM strategy_signals WHERE active=1 AND expires_at>? ORDER BY id DESC", (current,)).fetchall()
    return jsonify([dict(row, active=True) for row in rows])


@app.get("/api/admin/signals")
@admin_required
def admin_signals():
    signals()
    with db() as connection: rows = connection.execute("SELECT * FROM strategy_signals ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify([dict(row, active=bool(row["active"])) for row in rows])


@app.post("/api/admin/signals")
@admin_required
def create_signal():
    payload = request.get_json(silent=True) or {}
    symbol = str(payload.get("symbol", "")).upper().strip()
    direction = str(payload.get("direction", "")).upper()
    timeframe = str(payload.get("timeframe", "")).lower()
    try: duration = int(payload.get("durationMinutes", 60))
    except (TypeError, ValueError): return jsonify(error="durationMinutes must be an integer"), 400
    if not symbol or direction not in {"LONG", "SHORT", "WATCH"} or timeframe not in {"15m", "1h", "4h"} or not 1 <= duration <= 10080:
        return jsonify(error="invalid signal fields"), 400
    created = now(); expires = created + timedelta(minutes=duration)
    with db() as connection:
        cursor = connection.execute("INSERT INTO strategy_signals(symbol,direction,timeframe,note,created_at,expires_at,active) VALUES(?,?,?,?,?,?,1)", (symbol, direction, timeframe, str(payload.get("note", "")), iso(created), iso(expires)))
    return jsonify(id=cursor.lastrowid, symbol=symbol, direction=direction, timeframe=timeframe, expiresAt=iso(expires), active=True), 201


@app.delete("/api/admin/signals/<int:signal_id>")
@admin_required
def expire_signal(signal_id):
    with db() as connection: connection.execute("UPDATE strategy_signals SET active=0 WHERE id=?", (signal_id,))
    return jsonify(expired=True)


@app.post("/api/orders")
def create_order():
    payload = request.get_json(silent=True) or {}
    try:
        symbol = str(payload["symbol"]).upper(); side = str(payload["side"]).upper(); order_type = str(payload.get("type", "MARKET")).upper(); quantity = float(payload["quantity"]); price = float(payload["price"]) if payload.get("price") not in (None, "") else None; leverage = int(payload.get("leverage", 1))
    except (KeyError, TypeError, ValueError): return jsonify(error="invalid order fields"), 400
    if side not in {"BUY", "SELL", "LONG", "SHORT"} or order_type not in {"MARKET", "LIMIT"} or quantity <= 0 or not 1 <= leverage <= 125: return jsonify(error="invalid order parameters"), 400
    with db() as connection:
        cursor = connection.execute("INSERT INTO orders(user_id,wallet_address,symbol,side,order_type,quantity,price,leverage,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (payload.get("userId"), payload.get("walletAddress"), symbol, side, order_type, quantity, price, leverage, "ACCEPTED", iso(now())))
    return jsonify(id=cursor.lastrowid, status="ACCEPTED", execution="ledger-only; connect a reviewed execution adapter"), 201


@app.get("/api/orders")
def orders():
    with db() as connection: rows = connection.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify([dict(row) for row in rows])


@app.get("/api/admin/deposits")
@admin_required
def admin_deposits():
    with db() as connection: rows = connection.execute("SELECT * FROM deposits ORDER BY id DESC LIMIT 500").fetchall()
    return jsonify([dict(row) for row in rows])


@app.get("/api/admin/wallet-summary")
@admin_required
def wallet_summary():
    with db() as connection:
        pending = connection.execute("SELECT COUNT(*) FROM deposits WHERE status='pending'").fetchone()[0]
        confirmed = connection.execute("SELECT COUNT(*) FROM deposits WHERE status='confirmed'").fetchone()[0]
    return jsonify(pendingDeposits=pending, confirmedDeposits=confirmed, evmBalance="server adapter required", tronBalance="server adapter required")


@app.post("/api/admin/deposits/scan")
@admin_required
def scan_deposits():
    return jsonify(queued=True, message="Configure chain scanner workers and verify confirmations before crediting balances"), 202


@app.post("/api/admin/deposit-wallets")
@admin_required
def create_deposit_wallet():
    payload = request.get_json(silent=True) or {}; user_id = payload.get("userId"); network = payload.get("network")
    if not user_id or network not in {"evm", "tron", "solana"}: return jsonify(error="userId and network (evm, tron, or solana) are required"), 400
    provider_url = os.getenv("DEPOSIT_WALLET_PROVIDER_URL")
    if not provider_url: return jsonify(error="DEPOSIT_WALLET_PROVIDER_URL is not configured; refusing to create an unmanaged wallet"), 503
    try:
        response = requests.post(provider_url, json={"userId": user_id, "network": network}, headers={"Authorization": f"Bearer {os.environ['DEPOSIT_WALLET_PROVIDER_TOKEN']}"}, timeout=15); response.raise_for_status(); result = response.json(); address = result.get("address")
        if not address: return jsonify(error="wallet provider returned no address"), 502
    except (requests.RequestException, KeyError, ValueError) as error: return jsonify(error=f"wallet provider error: {error}"), 502
    with db() as connection: connection.execute("INSERT OR REPLACE INTO deposit_wallets(user_id,network,address,provider_reference,created_at) VALUES(?,?,?,?,?)", (user_id, network, address, result.get("id"), iso(now())))
    return jsonify(userId=user_id, network=network, address=address), 201


@app.post("/api/admin/deposits/webhook")
def deposit_webhook():
    secret = os.getenv("BLOCKCHAIN_WEBHOOK_SECRET")
    if secret and request.headers.get("X-Webhook-Secret") != secret: return jsonify(error="invalid webhook secret"), 401
    payload = request.get_json(silent=True) or {}; required = ["network", "asset", "amount", "txHash"]
    if any(not payload.get(key) for key in required) or payload["network"] not in {"evm", "tron", "solana"}: return jsonify(error="network, asset, amount and txHash are required"), 400
    with db() as connection: connection.execute("INSERT OR IGNORE INTO deposits(user_id,network,asset,amount,tx_hash,address,status,confirmations,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (payload.get("userId"), payload["network"], payload["asset"], str(payload["amount"]), payload["txHash"], payload.get("address"), payload.get("status", "pending"), int(payload.get("confirmations", 0)), iso(now()), iso(now())))
    return jsonify(accepted=True), 202


# Solscan Pro proxy. The API key never reaches the browser.
SOLSCAN_ENDPOINTS = {
    "account/detail", "account/transfer", "account/transactions", "account/token-accounts", "account/portfolio",
    "account/defi/activities", "account/balance_change", "token/transfer", "token/meta", "token/price",
    "token/markets", "transaction/detail", "transaction/actions", "transaction/fees", "block/last", "block/detail",
    "market/list", "market/info", "market/volume", "program/list", "monitor/usage"
}


def solscan_request(endpoint, params):
    api_key = os.getenv("SOLSCAN_API_KEY")
    if not api_key: return jsonify(error="SOLSCAN_API_KEY is not configured on the server"), 503
    if endpoint not in SOLSCAN_ENDPOINTS: return jsonify(error="Solscan endpoint is not allowlisted"), 404
    try:
        response = requests.get(f"{SOLSCAN_BASE_URL}/{endpoint}", params=params, headers={"token": api_key}, timeout=15)
        content = response.json()
    except (requests.RequestException, ValueError) as error:
        return jsonify(error=f"Solscan request failed: {error}"), 502
    return jsonify(content), response.status_code


@app.get("/api/admin/solscan/<path:endpoint>")
@admin_required
def admin_solscan(endpoint):
    return solscan_request(endpoint, request.args.to_dict(flat=True))


@app.get("/api/admin/solscan-status")
@admin_required
def solscan_status():
    return jsonify(configured=bool(os.getenv("SOLSCAN_API_KEY")), baseUrl=SOLSCAN_BASE_URL, costPerRequestCU=100)


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG", "0") == "1")
