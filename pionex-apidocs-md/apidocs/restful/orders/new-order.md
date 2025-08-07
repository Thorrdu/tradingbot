# New Order

Copy

```
POST /api/v1/trade/order
```

Permission: Trade

weight: 1

Request parameters

Name

Type

Mandatory

Description

symbol

string

YES

symbol

side

string

YES

BUY / SELL

type

string

YES

LIMIT / MARKET

clientOrderId

string

NO

Client id, consisting of upper and lower case letters / numbers / hyphen, maximum 64 bits.

size

string

NO

Quantity. Required in limit order and market sell order.

price

string

NO

Price. Required in limit order.

amount

string

NO

Buying amount. Required in market buy order.

IOC

boolean

NO

Default `false` .

Response format

Name

Type

Description

orderId

number

Order id.

clientOrderId

string

Client id.

Caution:

Error code:

* TRADE\_INVALID\_SYMBOL Invalid symbol.
* TRADE\_PARAMETER\_ERROR Parameter error.
* TRADE\_NOT\_ENOUGH\_MONEY Price amount higher than available balance.
* TRADE\_PRICE\_FILTER\_DENIED Price too low or too high.
* TRADE\_SIZE\_FILTER\_DENIED Invalid quantity.
* TRADE\_AMOUNT\_FILTER\_DENIED Invalid amount of market buy order or invalid price \* size.
* TRADE\_REPEAT\_CLIENT\_ORDER\_ID Duplicated clientOrderId.
* TRADE\_OPEN\_ORDER\_EXCEED\_LIMIT The number of open orders exceed the maximum limit.
* TRADE\_OPERATION\_DENIED Operation denied.

Request example

Copy

```
POST https://{site}/api/v1/trade/order
{
  "clientOrderId":  "9e3d93d6-e9a4-465a-a39c-2e48568fe194",
  "symbol":  "BTC_USDT",
  "side":  "BUY",
  "type":  "LIMIT",
  "size":  "0.1",
  "price":  "30000",
  "IOC":  true
}
```

Response example

Copy

```
{ 
  "data": {
    "orderId": 1234567890,
    "clientOrderId":  "9e3d93d6-e9a4-465a-a39c-2e48568fe194"
  },
  "result": true,
  "timestamp": 1566691672311
}
```

[PreviousOrders](https://pionex-doc.gitbook.io/apidocs/restful/orders)[NextNew Multiple Order](https://pionex-doc.gitbook.io/apidocs/restful/orders/new-multiple-order)

Last updated 1 year ago
