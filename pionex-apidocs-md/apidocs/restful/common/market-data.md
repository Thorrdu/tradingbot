# Market Data

Copy

```
GET /api/v1/common/symbols
```

Weight: 5

Request parameter

Name

Type

Mandatory

Description

symbols

string

No

Concatenate multiple symbols with ','

type

string

No

Type, if the symbol is specified, the type is irrelevant. If the symbol is not specified, the default is SPOT, with the possible values being SPOT / PERP.

Response format

Name

Type

Description

symbols

array

Collection of symbols, sorted by symbol in ascending order.

symbol

string

Symbol.

name

string

Name, only for PERP.

type

string

SPOT / PERP.

baseCurrency

string

Base coin.

quoteCurrency

string

Quote coin.

basePrecision

number

Precision digits of base currency price.

quotePrecision

number

Precision digits of quote currency price.

amountPrecision

number

Precision digits of the amount of market price buying order.

minNotional

string

Only for PERP.

minAmount

string

Minimum amount of the order, only for SPOT

minTradeSize

string

Minimum limit order quantity.

maxTradeSize

string

Maximum limit order quantity.

minTradeDumping

string

Minimum quantity of market price selling order.

maxTradeDumping

string

Maximum quantity of market price selling order.

buyCeiling

string

Maximum ratio of buying price, cannot be higher than a multiple of the latest highest buying price.

sellFloor

string

Minimum ratio of selling price, cannot be lower than a multiple of the latest lowest selling price.

enable

boolean

Enable trading.

maxImpactMarket

string

Max impact price of market order, only for PERP.

liquidationFeeRate

string

Liquidation fee rate, only for PERP.

Caution

Error code

Request example

Copy

```
GET https://{site}/api/v1/common/symbols?symbol=BTC_USDT
```

Response example

Copy

```
{ 
  "data": {
    "symbols":[
      {
        "symbol": "BTC_USDT",
        "type": "SPOT",
        "baseCurrency": "BTC",
        "quoteCurrency": "USDT",
        "basePrecision": 6,
        "quotePrecision": 2,
        "amountPrecision": 8,
        "minAmount": "10",
        "minTradeSize": "0.000001",
        "maxTradeSize": "1000",
        "minTradeDumping": "0.000001",
        "maxTradeDumping": "100",
        "enable": true,
        "buyCeiling": "1.1",
        "sellFloor": "0.9"
      }
    ]
  },
  "result": true,
  "timestamp": 1566676132311
}
```

[PreviousCommon](https://pionex-doc.gitbook.io/apidocs/restful/common)[NextAccount](https://pionex-doc.gitbook.io/apidocs/restful/account)

Last updated 1 year ago
