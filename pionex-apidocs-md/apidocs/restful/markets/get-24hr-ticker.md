# Get 24hr Ticker

Copy

```
GET /api/v1/market/tickers
```

Weight: 1

Request parameters

Name

Type

Mandatory

Description

symbol

string

No

Symbol.

type

string

No

Type, if the symbol is specified, the type is irrelevant. If the symbol is not specified, the default is SPOT, with the possible values being SPOT / PERP.

Response format

Name

Type

Description

tickers

array

Collection of tickers.

symbol

string

Symbol.

time

number

Timestamp in millisecond.

open

string

Open price.

close

string

Close price.

high

string

Highest price.

low

string

Lowest price.

volume

string

24-hour total trading volume

amount

string

24-hour total trading amount

count

string

24-hour total trading count

Error code

* MARKET\_INVALID\_SYMBOL Invalid symbol.
* MARKET\_PARAMETER\_ERROR Parameter error.

Request example

Copy

```
GET https://{site}/api/v1/market/tickers
```

Response example

Copy

```
{ 
  "data": {
    "tickers": [
      {
        "symbol": "BTC_USDT",
        "time": 1545291675000,
        "open": "7962.62",
        "close": "7952.32",
        "high": "7971.61",
        "low": "7950.29",
        "volume": "1.537",
        "amount": "12032.56",
        "count": 271585
      },
      {
        "symbol": "ETH_USDT",
        "time": 1545291675000,
        "open": "1963.62",
        "close": "1852.22",
        "high": "1971.11",
        "low": "1850.23",
        "volume": "100.532",
        "amount": "112012.51",
        "count": 432211
      }  
    ]
  },
  "result": true,
  "timestamp": 1566691672311
}
```

[PreviousGet Depth](https://pionex-doc.gitbook.io/apidocs/restful/markets/get-depth)[NextGet Book Ticker](https://pionex-doc.gitbook.io/apidocs/restful/markets/get-book-ticker)

Last updated 1 year ago
