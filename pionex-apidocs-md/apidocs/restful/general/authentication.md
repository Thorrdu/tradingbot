# Authentication

### Signature Description

There is a high risk of API requests being tampered with during transmission over the internet. Except for public endpoints (base information, market data), private endpoints must be signed and authenticated with your API Key to verify that parameters or values have not been modified in transit.

Endpoints are marked their corresponding weight value and permission.

Newly created API Key needs to be assigned permissions. Each API Key requires the appropriate permission(s) to access the corresponding endpoint. Please check required permission types before using the endpoints, and make sure your API Key has the appropriate permissions.

### Signing

1. Get current millisecond `timestamp`.
2. Set query parameters as key-value pairs: `key=value` (signature related value must not be URL-encoded).
3. Sort the key-value pairs in ascending ASCII order by key and concatenate with `&` (include `timestamp`).
4. Concatenate above result after `PATH` with `?` to generate `PATH_URL`.
5. Concatenate `METHOD` and `PATH_URL`.
6. Concatenate related entity body of `POST` and `DELETE` after step 5. Skip this step if there is no entity body.
7. Use `API Secret` and the above result to generate `HMAC SHA256` code, then convert it to hexadecimal.
8. Assign the hex result to `PIONEX-SIGNATURE`, add it to `Header` and send request.

Example:

User's `API Secret` and `timestamp` are:

Copy

```
Secret： NFqv4MB3hB0SOiEsJNDP9e0jDdKPWbDqS_Z1dbU4

timestamp： 1655896754515
```

The base part of request to query the order list is:

Copy

```
GET /api/v1/trade/allOrders?symbol=BTC_USDT&limit=1
```

Step 1, get current timestamp

Copy

```
timestamp=1655896754515
```

Step 2, set query parameters as key-value pairs: `key=value`

Copy

```
symbol=BTC_USDT
limit=1
timestamp=1655896754515
```

Step 3, Sort the key-value pairs in ascending ASCII order by key and concatenate with `&`

Copy

```
limit=1&symbol=BTC_USDT&timestamp=1655896754515
```

Step 4, concatenate above result after `PATH` with `?` to generate `PATH_URL`.

Copy

```
/api/v1/trade/allOrders?limit=1&symbol=BTC_USDT&timestamp=1655896754515
```

Step 5, concatenate `METHOD` and `PATH_URL`.

Copy

```
GET/api/v1/trade/allOrders?limit=1&symbol=BTC_USDT&timestamp=1655896754515
```

Step 6, Concatenate related entity body of `POST` and `DELETE` after step 5. Skip this step if there is no entity body.

Copy

```
b'GET/api/v1/trade/allOrders?limit=1&symbol=BTC_USDT&timestamp=1655896754515{"symbol": "BTC_USDT"}'
```

Step 7, Use `API Secret` and the above result to generate `HMAC SHA256` code, then convert it to hexadecimal.

Copy

```
ec83d21e1237cbe7e0172f79c0e3a4741c86f6b201ba762f21149bf195519be1    //PIONEX-SIGNATURE
```

[PreviousRate Limit](https://pionex-doc.gitbook.io/apidocs/restful/general/rate-limit)[NextCommon](https://pionex-doc.gitbook.io/apidocs/restful/common)

Last updated 3 years ago
