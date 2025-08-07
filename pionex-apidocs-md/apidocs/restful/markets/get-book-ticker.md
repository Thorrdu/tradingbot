# Get Book Ticker

Copy

```
GET /api/v1/market/bookTickers
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

Type, if the symbol is specified, the type is irrelevant. If the symbol is not specified, the default is PERP, with the possible values being SPOT / PERP.

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

bidPrice

number

Best bid price.

bidSize

string

Volume at the best bid price.

askPrice

string

Best ask price.

askSize

string

Volume at the best ask price.

timestamp

string

Timestamp in millisecond.

Error code

* MARKET\_INVALID\_SYMBOL Invalid symbol.
* MARKET\_PARAMETER\_ERROR Parameter error.

Request example

Copy

```
GET https://{site}/api/v1/market/bookTicker
```

Response example

Copy

```
{ 
  "data": {
    "tickers": [
      
    ]
  },
  "result": true,
  "timestamp": 1566691672311
}
```

[PreviousGet 24hr Ticker](https://pionex-doc.gitbook.io/apidocs/restful/markets/get-24hr-ticker)[NextGet Klines](https://pionex-doc.gitbook.io/apidocs/restful/markets/get-klines)

Last updated 1 year ago
