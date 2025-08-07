# Get Fills

Copy

```
GET /api/v1/trade/fills
```

Permission: Read

Weight: 5

Request parameters

Name

Type

Mandatory

Description

symbol

string

YES

Symbol.

startTime

number

NO

Start time in millisecond.

endTime

number

NO

End time in millisecond.

Response format

Name

Type

Description

fills

array

Collection of filled orders, sorted by filled time in descending order

id

number

Filled id.

orderId

number

Order id.

symbol

string

Symbol.

side

string

BUY / SELL.

role

string

TAKER / MAKER.

price

string

Price of fill.

size

string

Quantity of fill.

fee

string

Transaction fee.

feeCoin

string

Currency of transaction fee.

timestamp

number

Fill timestamp in millisecond.

Caution

When the number of orders in time range exceeds 100, return the latest 100 fills.

The self-dealing transaction will result in two transaction records, one for TAKER and the other for MAKER.

Error code

* TRADE\_INVALID\_SYMBOL Invalid symbol.
* TRADE\_PARAMETER\_ERROR Parameter error.

Request example

Copy

```
GET https://{site}/api/v1/trade/fills?symbol=BTC_USDT
```

Response example

Copy

```
{ 
  "data": {
    "fills":[
      {
        "id": 9876543210,
        "orderId": 123456789,
        "symbol": "BTC_USDT",
        "side": "SELL",
        "role":  "TAKER",
        "price": "30000.00",
        "size": "0.1000",
        "fee":  "0.15",
        "feeCoin":  "USDT",
        "timestamp": 1566676132311
      },
      {
        "id": 9876543200,
        "orderId": 123456789,
        "symbol": "BTC_USDT",
        "side": "SELL",
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

[PreviousGet All Orders](https://pionex-doc.gitbook.io/apidocs/restful/orders/get-all-orders)[NextGet Fills By Order Id](https://pionex-doc.gitbook.io/apidocs/restful/orders/get-fills-by-order-id)

Last updated 1 year ago
