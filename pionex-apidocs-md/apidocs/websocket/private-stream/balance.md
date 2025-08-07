# Balance

This topic streams your assets.

You can subscribe to it on a private connection by sending

Copy

```
{
  "op": "SUBSCRIBE",
  "topic":  "BALANCE"
}
```

Message example

Copy

```
{
  "topic":  "BALANCE",
  "data": {
    "balances": [
      {
        "coin": "BTC",
        "free": "0.9000000",
        "frozen": "0.00000000"
      },
      {
        "coin": "USDT",
        "free": "100.00000000",
        "frozen": "900.00000000"
      }
    ],
    "timestamp": 1566676132311
  },
  "timestamp":1566691672311
}
```

[PreviousFill](https://pionex-doc.gitbook.io/apidocs/websocket/private-stream/fill)

Last updated 2 years ago
