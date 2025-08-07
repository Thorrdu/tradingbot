# Trade

The TRADE topic provides data on all trades in the market. Up to 100 trades per message, sorted by timestamp in descending order.

You can subscribe to it on a public connection by sending

Copy

```
{
  "op": "SUBSCRIBE",
  "topic":  "TRADE", 
  "symbol": "BTC_USDT"
}
```

Data field contains

* `symbol`: Symbol.
* `tradeId`: Trade id.
* `price`: Price of the trade.
* `size`: Quantity of the trade.
* `side`: BUY / SELL. The direction of BUY or SELL of trade are from the liquidity TAKER's perspective.
* `timestamp`: Filled timestamp in millisecond.

Message example

Copy

```
{
  "topic": "TRADE",
  "symbol": "BTC_USDT"
  "data": [
    {
      "symbol": "BTC_USDT",
      "tradeId": "600848671",
      "price": "7962.62",
      "size": "0.0122",
      "side": "BUY",
      "timestamp": 1566691672311
    },
    {
      "symbol": "BTC_USDT",
      "tradeId": "600848672",
      "price": "7962.62",
      "size": "0.0322",
      "side": "BUY",
      "timestamp": 1566691672311
    },
    {
      "symbol": "BTC_USDT",
      "tradeId": "600848673",
      "price": "7962.62",
      "size": "0.0132",
      "side": "BUY",
      "timestamp": 1566691672311
    }
  ]
  "timestamp":1566691672311
}
```

###

[PreviousPublic Stream](https://pionex-doc.gitbook.io/apidocs/websocket/public-stream)[NextDepth](https://pionex-doc.gitbook.io/apidocs/websocket/public-stream/depth)

Last updated 3 years ago
