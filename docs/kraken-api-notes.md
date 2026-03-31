# Kraken API Reference

Full wire protocol detail for `data/backfill.py` and `data/feed.py`.

## Public REST (backfill)

- Endpoint: `GET https://api.kraken.com/0/public/OHLC?pair=ETHUSD&interval=15&since=<unix_ts>`
- Max 720 candles per request
- Response format:
  ```json
  {
    "error": [],
    "result": {
      "ETHUSD": [
        [time, open, high, low, close, vwap, volume, count],
        ...
      ],
      "last": <ts>
    }
  }
  ```
- No `Authorization` header needed

## Public WebSocket (live feed)

- URL: `wss://ws.kraken.com`
- Subscribe message:
  ```json
  {"event": "subscribe", "pair": ["ETH/USD"], "subscription": {"name": "ohlc", "interval": 15}}
  ```
- Incoming message format:
  ```
  [channelID, [beginTime, endTime, open, high, low, close, vwap, volume, count], "ohlc-15", "ETH/USD"]
  ```
- Candle-close detection: emit the old candle when `beginTime` in the new message differs from the previous message's `beginTime`
- No auth needed for market data subscriptions

## Symbol Format

| Context | Format |
|---------|--------|
| REST params (`pair=`) | `ETHUSD` (no slash) |
| WebSocket subscription (`pair:`) | `ETH/USD` (with slash) |

## Live Trading Auth (Phase 6 only)

Private REST endpoints use HMAC-SHA512. API key + secret go in `secrets/secrets.yaml`.
Not needed until Phase 6.

## History

Originally targeted Coinbase Advanced Trade. Switched to Kraken (March 2026) because
Kraken's public market data endpoints require zero authentication, eliminating CDP JWT
auth complexity for Phases 1–5.
