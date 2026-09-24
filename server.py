import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "trading_platform.db"))
app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")
CORS(app, resources={r"/api/*": {"origins": os.getenv("CORS_ORIGINS", "*").split(",")}})


def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                wallet_address TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                wallet_address TEXT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL CHECK(side IN ('BUY','SELL','LONG','SHORT')),
                order_type TEXT NOT NULL CHECK(order_type IN ('MARKET','LIMIT')),
                quantity REAL NOT NULL,
                price REAL,
                leverage INTEGER DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'ACCEPTED',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS deposit_wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                network TEXT NOT NULL CHECK(network IN ('evm','tron')),
                address TEXT NOT NULL,
                provider_reference TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, network)
            );
            CREATE TABLE IF NOT EXISTS deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                network TEXT NOT NULL,
                asset TEXT NOT NULL,
                amount TEXT NOT NULL,
                tx_hash TEXT NOT NULL UNIQUE,
                address TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                confirmations INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )


def now():
    return datetime.now(timezone.utc).isoformat()


def admin_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        configured = os.getenv("ADMIN_API_TOKEN")
        supplied = request.headers.get("X-Admin-Token") or request.headers.get("Authorization", "").removeprefix("Bearer ")
        # Local development remains convenient, but production must configure a token.
        if configured and supplied != configured:
            return jsonify({"error": "admin authentication required"}), 401
        if not configured and request.remote_addr not in {"127.0.0.1", "::1"}:
            return jsonify({"error": "set ADMIN_API_TOKEN before exposing admin APIs"}), 403
        return function(*args, **kwargs)
    return wrapper


@app.get("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/enterprise-mdr")
def enterprise_mdr():
    return send_from_directory(BASE_DIR, "enterprise-mdr.html")


@app.get("/enterprise-mdr-admin")
def enterprise_mdr_admin():
    return send_from_directory(BASE_DIR, "enterprise-mdr-admin.html")


@app.get("/enterprise")
def enterprise():
    return send_from_directory(BASE_DIR, "enterprise.html")


@app.get("/enterprise-wallet-fixed")
def wallet():
    return send_from_directory(BASE_DIR, "enterprise-wallet-fixed.html")


@app.get("/favicon.ico")
def favicon():
    return send_from_directory(BASE_DIR, "mdr-icon.png", mimetype="image/png")


@app.get("/api/market")
@app.get("/api/ticker")
def market():
    # Replace this adapter with a licensed market-data provider in production.
    return jsonify([
        {"symbol": "BTC", "tvSymbol": "BINANCE:BTCUSDT", "price": 67432.18, "changePct": 1.88, "volume": "28.4B"},
        {"symbol": "ETH", "tvSymbol": "BINANCE:ETHUSDT", "price": 3421.55, "changePct": -1.22, "volume": "14.2B"},
        {"symbol": "SOL", "tvSymbol": "BINANCE:SOLUSDT", "price": 178.92, "changePct": 4.95, "volume": "5.1B"},
        {"symbol": "BNB", "tvSymbol": "BINANCE:BNBUSDT", "price": 790.89, "changePct": 0.51, "volume": "9.2B"},
    ])


@app.get("/api/portfolio")
def portfolio():
    return jsonify({"balance": 0, "positions": [], "notice": "Connect this endpoint to your custody or exchange ledger."})


@app.post("/api/orders")
def create_order():
    payload = request.get_json(silent=True) or {}
    try:
        symbol = str(payload["symbol"]).upper()
        side = str(payload["side"]).upper()
        order_type = str(payload.get("type", "MARKET")).upper()
        quantity = float(payload["quantity"])
        price = float(payload["price"]) if payload.get("price") not in (None, "") else None
        leverage = int(payload.get("leverage", 1))
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "symbol, side, quantity and valid order fields are required"}), 400
    if side not in {"BUY", "SELL", "LONG", "SHORT"} or order_type not in {"MARKET", "LIMIT"} or quantity <= 0 or not 1 <= leverage <= 125:
        return jsonify({"error": "invalid order parameters"}), 400
    order_status = "ACCEPTED"  # Risk checks and exchange/custody execution belong in a worker.
    with db() as connection:
        cursor = connection.execute(
            "INSERT INTO orders(user_id,wallet_address,symbol,side,order_type,quantity,price,leverage,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (payload.get("userId"), payload.get("walletAddress"), symbol, side, order_type, quantity, price, leverage, order_status, now()),
        )
        order_id = cursor.lastrowid
    return jsonify({"id": order_id, "status": order_status, "execution": "ledger-only; configure an execution adapter"}), 201


@app.get("/api/orders")
def list_orders():
    with db() as connection:
        rows = connection.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify([dict(row) for row in rows])


@app.get("/api/admin/deposits")
@admin_required
def admin_deposits():
    with db() as connection:
        rows = connection.execute("SELECT * FROM deposits ORDER BY id DESC LIMIT 500").fetchall()
    return jsonify([dict(row) for row in rows])


@app.get("/api/admin/wallet-summary")
@admin_required
def wallet_summary():
    with db() as connection:
        pending = connection.execute("SELECT COUNT(*) FROM deposits WHERE status='pending'").fetchone()[0]
        confirmed = connection.execute("SELECT COUNT(*) FROM deposits WHERE status='confirmed'").fetchone()[0]
    return jsonify({"pendingDeposits": pending, "confirmedDeposits": confirmed, "evmBalance": "server adapter required", "tronBalance": "server adapter required"})


@app.post("/api/admin/deposits/scan")
@admin_required
def scan_deposits():
    # A production scanner should consume explorer webhooks or a queue and verify:
    # chain, recipient, token contract, amount, confirmations, and replay protection.
    return jsonify({"queued": True, "message": "Configure EVM/TRON scanner workers and API keys server-side."}), 202


@app.post("/api/admin/deposit-wallets")
@admin_required
def create_deposit_wallet():
    payload = request.get_json(silent=True) or {}
    user_id, network = payload.get("userId"), payload.get("network")
    if not user_id or network not in {"evm", "tron"}:
        return jsonify({"error": "userId and network (evm or tron) are required"}), 400
    provider_url = os.getenv("DEPOSIT_WALLET_PROVIDER_URL")
    if not provider_url:
        return jsonify({"error": "DEPOSIT_WALLET_PROVIDER_URL is not configured; refusing to create an unmanaged wallet"}), 503
    try:
        response = requests.post(provider_url, json={"userId": user_id, "network": network}, headers={"Authorization": f"Bearer {os.environ['DEPOSIT_WALLET_PROVIDER_TOKEN']}"}, timeout=15)
        response.raise_for_status()
        result = response.json()
        address = result.get("address")
        if not address:
            return jsonify({"error": "wallet provider returned no address"}), 502
    except (requests.RequestException, KeyError, ValueError) as error:
        return jsonify({"error": f"wallet provider error: {error}"}), 502
    with db() as connection:
        connection.execute("INSERT OR REPLACE INTO deposit_wallets(user_id,network,address,provider_reference,created_at) VALUES(?,?,?,?,?)", (user_id, network, address, result.get("id"), now()))
    return jsonify({"userId": user_id, "network": network, "address": address}), 201


@app.post("/api/admin/deposits/webhook")
def deposit_webhook():
    secret = os.getenv("BLOCKCHAIN_WEBHOOK_SECRET")
    if secret and request.headers.get("X-Webhook-Secret") != secret:
        return jsonify({"error": "invalid webhook secret"}), 401
    payload = request.get_json(silent=True) or {}
    required = ["network", "asset", "amount", "txHash"]
    if any(not payload.get(key) for key in required) or payload["network"] not in {"evm", "tron"}:
        return jsonify({"error": "network, asset, amount and txHash are required"}), 400
    with db() as connection:
        connection.execute("INSERT OR IGNORE INTO deposits(user_id,network,asset,amount,tx_hash,address,status,confirmations,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (payload.get("userId"), payload["network"], payload["asset"], str(payload["amount"]), payload["txHash"], payload.get("address"), payload.get("status", "pending"), int(payload.get("confirmations", 0)), now(), now()))
    return jsonify({"accepted": True}), 202


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG", "0") == "1")
