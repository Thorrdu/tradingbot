# Get Trades

Copy

```
GET /api/v1/market/trades
```

Weight: 1

Request parameters

Name

Type

Mandatory

Description

symbol

string

YES

Symbol.

limit

number

NO

Default: 100.
Range: 10 - 500

Response format

Name

Type

Description

trades

array

Collection of latest real-time transaction, sorted by timestamp in descending order.

symbol

string

Symbol.

tradeId

string

Trade id.

price

string

Price of the trade.

size

string

Quantity of the trade.

side

string

BUY / SELL

timestamp

string

Filled timestamp in millisecond.

Caution: The direction of BUY or SELL is from the liquidity TAKER’s perspective.

Error code

* MARKET\_INVALID\_SYMBOL Invalid symbol.
* MARKET\_PARAMETER\_ERROR Parameter error

Request example

Copy

```
GET https://{site}/api/v1/market/trades?symbol=BTC_USDT&limit=5
```

Response example

Copy

```
{ 
  "data": {
    "trades": [
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
        "tradeId": "600848670",
        "price": "7960.12",
        "size": "0.0198",
        "side": "BUY",
        "timestamp": 1566691672311
      }
    ]
  },
  "result": true,
  "timestamp": 1566691672311
}
```

[PreviousMarkets](https://pionex-doc.gitbook.io/apidocs/restful/markets)[NextGet Depth](https://pionex-doc.gitbook.io/apidocs/restful/markets/get-depth)

Last updated 3 years ago
