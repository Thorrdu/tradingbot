# Fill

This topic streams your fills across all markets.

You can subscribe to it on a private connection by sending

Copy

```
{
  "op": "SUBSCRIBE",
  "topic":  "FILL", 
  "symbol": "BTC_USDT"
}
```

Message example

Copy

```
{
  "topic":  "FILL",
  "symbol": "BTC_USDT",
  "data": {
    "id": 9876543210,
    "orderId": 1234567890,
    "symbol": "BTC_USDT",
    "side": "BUY",
    "role":  "TAKER",
    "price": "30000.00",
    "size": "0.1000",
    "fee":  "0.15",
    "feeCoin":  "USDT",
    "timestamp": 1566676132311
  },
  "timestamp":1566691672311
}
```

[PreviousOrder](https://pionex-doc.gitbook.io/apidocs/websocket/private-stream/order)[NextBalance](https://pionex-doc.gitbook.io/apidocs/websocket/private-stream/balance)

Last updated 3 years ago
