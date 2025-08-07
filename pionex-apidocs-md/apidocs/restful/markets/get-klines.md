# Get Klines

Copy

```
GET /api/v1/market/klines
```

Weight: 1

Request parameters

Name

Type

Mandatory

Description

symbol

string

YES

Symbol.

interval

string

YES

1M，5M，15M，30M，60M，4H，8H，12H，1D

endTime

number

NO

End time in millisecond

limit

number

NO

Default 100, range: 1-500.

Response format

Name

Type

Description

klines

array

Collection of klines.

time

number

Timestamp in millisecond.

open

string

Open price.

close

string

Close price.

high

string

Highest price.

low

string

Lowest price.

volume

string

Total trading volume

Error code

Request example

Copy

```
GET https://{site}/api/v1/market/klines
```

Response example

Copy

```
{
  "result": true,
  "data": {
    "klines": [
      {
        "time": 1691649240000,
        "open": "1851.27",
        "close": "1851.32",
        "high": "1851.32",
        "low": "1851.27",
        "volume": "0.542"
      }
    ]
  },
  "timestamp": 1691649271544
}
```

[PreviousGet Book Ticker](https://pionex-doc.gitbook.io/apidocs/restful/markets/get-book-ticker)[NextGeneral Info](https://pionex-doc.gitbook.io/apidocs/websocket/general-info)

Last updated 1 year ago
