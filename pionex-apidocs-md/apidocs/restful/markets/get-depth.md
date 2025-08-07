# Get Depth

Copy

```
GET /api/v1/market/depth
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

Default:20.
Range: 1 - 1000

Response format

Name

Type

Description

bids

array

Collection of bid order [price, quantity], sorted by price in descending order.

asks

array

Collection of ask order (price, quantity), sorted by price in ascending order.

updateTime

number

Update timestamp in millisecond.

Error code

* MARKET\_INVALID\_SYMBOL Invalid symbol.
* MARKET\_PARAMETER\_ERROR Parameter error.

Request example

Copy

```
GET https://{site}/api/v1/market/depth?symbol=BTC_USDT&limit=5
```

Response example

Copy

```
{ 
  "data": {
    "bids": [
        ["29658.37", "0.0123"],
        ["29658.35", "1.1234"],
        ["29657.99", "2.2345"],
        ["29657.56", "6.3456"],
        ["29656.13", "8.4567"]
    ],
    "asks": [
        ["29658.47", "0.0345"],
        ["29658.65", "1.0456"],
        ["29658.89", "3.5567"],
        ["29659.43", "5.2678"],
        ["29659.98", "1.9789"]
    ]，
    "updateTime": 1566676132311
  },
  "result": true,
  "timestamp": 1566691672311
}
```

[PreviousGet Trades](https://pionex-doc.gitbook.io/apidocs/restful/markets/get-trades)[NextGet 24hr Ticker](https://pionex-doc.gitbook.io/apidocs/restful/markets/get-24hr-ticker)

Last updated 2 years ago
