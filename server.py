import os
import json
from flask import Flask, send_from_directory, jsonify, request
from flask_cors import CORS

# Configure Flask to serve static files from the current directory
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# --- STATIC ROUTE HANDLERS ---
@app.route('/')
def home():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/enterprise')
def serve_enterprise():
    return send_from_directory(app.static_folder, 'enterprise.html')

@app.route('/enterprise-mdr')
def serve_enterprise_mdr():
    return send_from_directory(app.static_folder, 'enterprise-mdr.html')

@app.route('/enterprise-wallet-fixed')
def serve_wallet():
    return send_from_directory(app.static_folder, 'enterprise-wallet-fixed.html')

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(app.static_folder, 'mdr-icon.png', mimetype='image/png')

@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory(app.static_folder, filename)

# --- API ENDPOINTS ---
@app.route('/api/ticker')
def get_ticker():
    # Placeholder ticker endpoint
    return jsonify([
        {"symbol": "BTCUSDT", "price": 86406.03, "change": 1.201},
        {"symbol": "ETHUSDT", "price": 2751.36, "change": 0.72},
        {"symbol": "SOLUSDT", "price": 118.73, "change": 1.792},
        {"symbol": "BNBUSDT", "price": 790.89, "change": 0.512}
    ])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
