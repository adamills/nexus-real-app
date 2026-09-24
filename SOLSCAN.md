### Solscan Pro integration

The Flask server exposes an authenticated, allowlisted Solscan proxy. The Solscan key stays server-side and is never embedded in frontend code.

Set in `.env`:

```env
SOLSCAN_BASE_URL=https://pro-api.solscan.io/v2.0
SOLSCAN_API_KEY=your_server_side_key
SOLANA_RPC_URL=your_mainnet_rpc
```

Check configuration:

```bash
curl -H "X-Admin-Token: $ADMIN_API_TOKEN" http://127.0.0.1:5000/api/admin/solscan-status
```

Example account transfer request:

```bash
curl -G -H "X-Admin-Token: $ADMIN_API_TOKEN" \
  --data-urlencode "address=YOUR_SOLANA_ADDRESS" \
  --data-urlencode "page=1" \
  --data-urlencode "page_size=10" \
  http://127.0.0.1:5000/api/admin/solscan/account/transfer
```

Example transaction detail request:

```bash
curl -G -H "X-Admin-Token: $ADMIN_API_TOKEN" \
  --data-urlencode "tx=YOUR_TRANSACTION_SIGNATURE" \
  http://127.0.0.1:5000/api/admin/solscan/transaction/detail
```

All requests cost the Solscan plan's documented CU amount. Add caching, queueing, exponential backoff, and RPC confirmation checks before using this for deposit crediting. Solscan does not generate wallets or sign transactions; use a custody/HD-wallet provider for those operations.
