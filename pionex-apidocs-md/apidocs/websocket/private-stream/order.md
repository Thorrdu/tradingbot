# Order

This topic streams updates to your orders across all markets.

Update Speed: Once every 250ms when there are multiple changes. Once every 5000ms when there is no change.

You can subscribe to it on a private connection by sending

Copy

```
{
  "op": "SUBSCRIBE",
  "topic":  "ORDER",
  "symbol": "BTC_USDT"
}
```

Message example

Copy

```
{
  "topic": "ORDER",
  "symbol": "BTC_USDT",
  "data": {
    "orderId": 1234567890,
    "symbol": "BTC_USDT",
    "type": "LIMIT",
    "side": "BUY",
    "price": "30000.00",
    "size": "0.1000",
    "filledSize": "0.0500",
    "filledAmount": "1500.00",
    "fee":  "0.15",
    "feeCoin": "USDT",
    "IOC":  false,
    "status": "OPEN",
    "clientOrderId":  "9e3d93d6-e9a4-465a-a39c-2e48568fe194"
    "createTime": 1566676132311,
    "updateTime": 1566676132311
  },
  "timestamp": 1566691672311
}
```

[PreviousPrivate Stream](https://pionex-doc.gitbook.io/apidocs/websocket/private-stream)[NextFill](https://pionex-doc.gitbook.io/apidocs/websocket/private-stream/fill)

Last updated 3 years ago
