# Backend integration

This repository now includes a Flask API for the MDR user panel and admin operations dashboard.

## Run locally

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
python server.py
```

Open `/enterprise-mdr` for the user trading panel and `/enterprise-mdr-admin` for the operations dashboard.

## Important production boundary

- The API records orders as `ACCEPTED` ledger entries; it does not pretend to execute trades. Connect a reviewed exchange/custody adapter and risk engine before enabling live execution.
- Etherscan/TRONScan keys and private keys must stay server-side. The admin UI only calls backend routes.
- Deposit addresses are created only through `DEPOSIT_WALLET_PROVIDER_URL`; the server refuses to invent unmanaged addresses.
- A production deployment must set `ADMIN_API_TOKEN`, use HTTPS, replace the development CORS setting, add authentication/authorization, rate limiting, audit logs, and a queue-backed chain scanner.
- `/api/admin/deposits/webhook` accepts explorer/custody events and uses a secret plus transaction-hash uniqueness to reduce replay risk. The worker must independently verify confirmations, destination, token contract, chain ID, and amount before crediting a user.

## Main routes

- `GET /api/market`
- `POST /api/orders`
- `GET /api/orders`
- `GET /api/admin/deposits`
- `POST /api/admin/deposits/scan`
- `GET /api/admin/wallet-summary`
- `POST /api/admin/deposit-wallets`
- `POST /api/admin/deposits/webhook`
