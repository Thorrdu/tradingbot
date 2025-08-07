# Get Balance

Copy

```
GET /api/v1/account/balances
```

Permission: Read

Weight: 1

Request parameters

None

Response format

Name

Type

Description

balances

array

Collection of account balances, sorted by coin in ascending order.

coin

string

Coin

free

string

Available balance, 8 decimal digits.

frozen

string

Frozen balance, 8 decimal digits.

Caution: The balances only includes the balances of the trading account, excluding the balances of bots and earn account. And the balance is simply to 8 decimal places without rounding.

Error code

Request example

Copy

```
GET https://{site}/api/v1/account/balances
```

Response example

Copy

```
{ 
  "data": {
    "balances": [
      {
        "coin": "BTC",
        "free": "0.9000000",
        "frozen": "0.00000000"
      },
      {
        "coin": "USDT",
        "free": "100.00000000",
        "frozen": "900.00000000"
      }
    ]
  },
  "result": true,
  "timestamp": 1566691672311
}
```

####

[PreviousAccount](https://pionex-doc.gitbook.io/apidocs/restful/account)[NextOrders](https://pionex-doc.gitbook.io/apidocs/restful/orders)

Last updated 2 years ago
