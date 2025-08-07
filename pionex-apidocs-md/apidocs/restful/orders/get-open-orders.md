# Get Open Orders

Copy

```
GET /api/v1/trade/openOrders
```

Permission: Read

Weight: 5

Request parameters

Name

Type

**M**andatory

**Description**

symbol

string

YES

Symbol.

Response format

Name

Type

Description

orders

array

Collection of open orders, sorted by createTime in descending order.

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

Order quantity

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

Source of order, MANUAL / API.

createTime

number

Create timestamp in millisecond.

updateTime

number

Update timestamp in millisecond.

Caution: The number of Open Orders of the same symbol cannot exceed 200.

Error code

* TRADE\_INVALID\_SYMBOL Invalid symbol
* TRADE\_PARAMETER\_ERROR Parameter error

Request example

Copy

```
GET https://{site}/api/v1/trade/openOrders?symbol=BTC_USDT
```

Response example

Copy

```
{ 
  "data": {
    "orders":[
      {
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
        "IOC": false,
        "clientOrderId":  "9e3d93d6-e9a4-465a-a39c-2e48568fe194",
        "source": "API",
        "createTime": 1566676132311,
        "updateTime": 1566676132311
      }
    ]
  },
  "result": true,
  "timestamp": 1566676132311
}
```

[PreviousCancel Order](https://pionex-doc.gitbook.io/apidocs/restful/orders/cancel-order)[NextGet All Orders](https://pionex-doc.gitbook.io/apidocs/restful/orders/get-all-orders)

Last updated 1 year ago
