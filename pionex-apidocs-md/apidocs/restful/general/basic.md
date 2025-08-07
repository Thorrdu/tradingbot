# Basic Info

RESTful endpoint URL: `https://api.pionex.com`

### General API information

* `timestamp` parameter in `query string`, `PIONEX-KEY` and `PIONEX-SIGNATURE` parameters in headers, are required in all `PRIVATE` request

Parameter

Field

Type

Description

timestamp

query

number

Request timestamp in millisecond.
Any timestamp older than 20,000 milliseconds or in the future is invalid

PIONEX-KEY

header

string

Account API Key.

PIONEX-SIGNATURE

header

string

Signature.
`GET` : `METHOD + PATH_URL + QUERY + TIMESTAMP`
`POST` and `DELETE` : `METHOD + PATH_URL + QUERY + TIMESTAMP + body`For further information, please refer to Authentication section

* For `GET` endpoint, additional parameter must be sent in `query string`
* For `POST` and `DELETE` endpoints, additional parameter must be sent in `request body`, `content-type` should be `application/json`
* 0 value of all `number` type parameters will be ignored.

### Response Message

* Responses of all RESTful endpoints are JSON data, which contains

Parameters

Name

Type

Description

result

boolean

`true` for success，`false` otherwise

timestamp

number

Response timestamp (millisecond)

* A successful response will contain business data

Name

Type

Description

data

object

Business data.

Example:

Copy

```
{
  "result": true,
  "data": {
    "orderId":  123456789
  },
  "timestamp":  1566691672311
}
```

* Failed response contains

Name

Type

Description

code

string

Error code (See description)

message

string

Error message

Example:

Copy

```
{
  "result": false,
  "code": "TRADE_INVAILD_SYMBOL",
  "message":  "Invalid symbol",
  "timestamp":  1566691672311
}
```

### Error Code

* APIKEY\_LOST
* SIGNATURE\_LOST
* IP*\_*NOT*\_*WHITELISTED
* INVALIE\_APIKEY
* INVALID\_SIGNATURE
* APIKEY\_EXPIRED
* INVALID\_TIMESTAMP
* PERMISSION\_DENIED

[PreviousGeneral Info](https://pionex-doc.gitbook.io/apidocs/restful/general)[NextRate Limit](https://pionex-doc.gitbook.io/apidocs/restful/general/rate-limit)

Last updated 3 years ago
