# New Multiple Order

Copy

```
POST /api/v1/trade/massOrder
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

orders

array

YES

Collection of orders, Up to a maximum of 20.

side

string

YES

BUY / SELL

type

string

YES

Only support LIMIT.

clientOrderId

string

NO

Client id, consisting of upper and lower case letters / numbers / hyphen, maximum 64 bits.

size

string

YES

Quantity.

price

string

YES

Price.

Response format

Name

Type

Description

orderIds

array

orderId

number

Order id.

clientOrderId

string

Client Id.

Caution:

A maximum of 20 orders at a time.

Error code:

Request example

Copy

```
POST https://{site}/uapi/v1/trade/massOrder
    {
      "symbol": "ETH_USDT_PERP",
      "orders": [
        {
          "side": "BUY",
          "type": "LIMIT",
          "clientOrderId": "137323758753278456966529045985602048290",
          "price": "1700",
          "size": "0.001"
        }
      ]
    }
```

Response example

Copy

```
{
    "result": true,
    "data": {
        "orderIds": [
        {
            "orderId": 11000614011208411,
            "clientOrderId": "137323758753278456966529045985602048290"
          }
        ]
  },
  "timestamp": 1691634429250
}
```

[PreviousNew Order](https://pionex-doc.gitbook.io/apidocs/restful/orders/new-order)[NextGet Order](https://pionex-doc.gitbook.io/apidocs/restful/orders/get-order)

Last updated 1 year ago
