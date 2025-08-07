# Depth

The DEPTH topic provides the latest market by price order book.

You can subscribe to it on a public connection by sending

Copy

```
{
  "op": "SUBSCRIBE",
  "topic":  "DEPTH", 
  "symbol": "BTC_USDT",
  "limit":  5 // Range: 1-100
}
```

Data field contains

* `bids`
* `asks`

The `bids` and `asks` are formatted like so: `[[best price, size at price], [next next best price, size at price], ...]`

Message example

Copy

```
{
  "topic": "DEPTH",
  "symbol": "BTC_USDT"
  "data": {
    "bids": [
      ["27964.01", "0.0675"],
      ["27963.23", "0.9111"],
      ["27961.52", "0.1022"],
      ["27960.00", "3.8891"],
      ["27958.13", "1.2008"]
    ],
    "asks": [
      ["27979.32", "0.0731"],
      ["27980.97", "1.0294"],
      ["27981.62", "2.5651"],
      ["27986.45", "1.2415"],
      ["27990.16", "1.9978"]
    ]  
  },
  "timestamp": 1566691672311
}
```

[PreviousTrade](https://pionex-doc.gitbook.io/apidocs/websocket/public-stream/trade)[NextPrivate Stream](https://pionex-doc.gitbook.io/apidocs/websocket/private-stream)

Last updated 3 years ago
