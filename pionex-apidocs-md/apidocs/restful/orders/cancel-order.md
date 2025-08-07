# Cancel Order

Copy

```
DELETE /api/v1/trade/order
```

Permission: Trade

Weight: 1

Request parameters

Name

Type

Mandatory

Description

symbol

string

YES

symbol

orderId

number

YES

order id to be cancelled

Response format: None

Error code

* TRADE\_INVALID\_SYMBOL Invalid symbol.
* TRADE\_PARAMETER\_ERROR Parameter error.
* TRADE\_OPERATION\_DENIED Operation denied.

Request example

Copy

```
DELETE https://{site}/api/v1/trade/order
{
  "symbol":  "BTC_USDT",
  "orderId":  1234567890
}
```

Response example

Copy

```
{ 
  "result": true,
  "timestamp": 1566691672311
}
```

[PreviousGet Order by Client Order Id](https://pionex-doc.gitbook.io/apidocs/restful/orders/get-order-by-client-order-id)[NextGet Open Orders](https://pionex-doc.gitbook.io/apidocs/restful/orders/get-open-orders)

Last updated 1 year ago
