# Get Fills By Order Id

Copy

```
GET /api/v1/trade/fillsByOrderId
```

Permission: Read

Weight: 5

Request parameters

Name

Type

Mandatory

Description

orderId

number

YES

Order id, return empty list if orderId not found.

fromId

number

NO

Return 100 (earlier) fills before this fill.
Return all earlier fills if there is insufficient number of fills.
If not specified, return the latest fills.

Response format

Name

Type

Description

fills

array

Collection of filled orders, sorted by filled time in descending order.

id

number

Fill id.

orderId

number

Order id.

symbol

string

Symbol.

side

string

BUY / SELL

role

string

TAKER / MAKER

price

string

Price of fill.

size

string

Price of fill.

fee

string

Transaction fee.

feeCoin

string

Currency of transaction fee.

timestamp

number

Fill timestamp in millisecond.

Error code

* TRADE\_INVALID\_SYMBOL Invalid symbol
* TRADE\_PARAMETER\_ERROR Parameter error

Request example

Copy

```
GET https://{site}/api/v1/trade/fillsByOrderId?symbol=BTC_USDT&orderId=22334455
```

Response example

Copy

```
{ 
  "data": {
    "fills":[
      {
        "id": 9876543210,
        "orderId": 22334455,
        "symbol": "BTC_USDT",
        "side": "BUY",
        "role":  "TAKER",
        "price": "30000.00",
        "size": "0.1000",
        "fee":  "0.15",
        "feeCoin":  "USDT",
        "timestamp": 1566676132311
      },
      {
        "id": 9876543200,
        "orderId": 22334455,
        "symbol": "BTC_USDT",
        "side": "BUY",
        "role":  "TAKER",
        "price": "29000.00",
        "size": "0.1200",
        "fee":  "0.145",
        "feeCoin":  "USDT",
        "timestamp": 1566676132310
      }
    ]
  },
  "result": true,
  "timestamp": 1566691672311
}
```

####

[PreviousGet Fills](https://pionex-doc.gitbook.io/apidocs/restful/orders/get-fills)[NextCancel all orders](https://pionex-doc.gitbook.io/apidocs/restful/orders/cancel-all-orders)

Last updated 1 year ago
