# Get Order

Copy

```
GET /api/v1/trade/order
```

Permission: Read

Weight： 1

Request parameter

Name

Type

Mandatory

Description

orderId

number

YES

order id

Response format

Name

Type

Description

orderId

number

Order id.

symbol

string

Symbol.

type

string

LIMIT / MARKET.

side

string

BUY / SELL.

price

string

Price.

size

string

Order quantity.

amount

string

The amount of market buy order.

filledSize

string

Filled quantity of order.

filledAmount

string

Filled amount of order.

fee

string

Transaction fee.

feeCoin

string

Currency of transaction fee.

status

string

OPEN / CLOSED.

IOC

boolean

IOC

clientOrderId

string

Client id.

source

string

Source of order, MANUAL / API

createTime

number

Create timestamp in millisecond.

updateTime

number

Update timestamp in millisecond.

Error code

* TRADE\_ORDER\_NOT\_FOUND Order not found.
* TRADE\_INVALID\_SYMBOL Invalid symbol.
* TRADE\_PARAMETER\_ERROR Parameter error.

Request example

Copy

```
GET https://{site}/api/v1/trade/order?symbol=BTC_USDT&orderId=1234567890
```

Response example

Copy

```
{ 
  "data": {
    "orderId": 1234567890,
    "symbol": "BTC_USDT",
    "type": "LIMIT",
    "side": "SELL",
    "price": "30000.00",
    "size": "0.1000",
    "filledSize": "0.0500",
    "filledAmount": "1500.00",
    "fee":  "0.15",
    "feeCoin":  "USDT",
    "status": "OPEN",
    "IOC":  false,
    "clientOrderId":  "9e3d93d6-e9a4-465a-a39c-2e48568fe194",
    "source": "API",
    "createTime": 1566676132311,
    "updateTime": 1566676132311
  },
  "result": true,
  "timestamp": 1566691672311
}
```

[PreviousNew Multiple Order](https://pionex-doc.gitbook.io/apidocs/restful/orders/new-multiple-order)[NextGet Order by Client Order Id](https://pionex-doc.gitbook.io/apidocs/restful/orders/get-order-by-client-order-id)

Last updated 1 year ago
