# General Info

### Connection Management

Private stream and public stream have different subscription path.

Private stream: `wss://ws.pionex.com/ws`

Public stream: `wss://ws.pionex.com/wsPub`

Subscribing to the private requires authentication, while public stream does not.

### Authentication Information

When subscribing to private stream, you need to send authentication parameters in query string

* `key`: user's API Key
* `timestamp`: timestamp in millisecond
* `signature`: concatenate `PATH_URL` and "`websocket_auth`" , then use the result to generate `HMAC SHA256` code.

Copy

```
wss://ws.pionex.com/ws?key=xxx-xx-xx&timestamp=1566691672311&signature=13e901247350e744353f4a7a479fd67181184a627b119352ec1b7a432925e772c
```

#### Signing

1. Get current millisecond `timestamp`.
2. Set query parameters as key-value pairs: `key=value` ( `key` and `timestamp`).
3. Sort the key-value pairs in ascending ASCII order by key and concatenate with & .
4. Concatenate above result after `PATH` with `?` to generate `PATH_URL.`
5. Concatenate "`websocket_auth`" after above result.
6. Use `API Secret` and the above result to generate `HMAC SHA256` code, then convert it to hexadecimal.
7. Assign the hex result to `signature`, add it to query parameter and send request.

Example

User's `API Key / Secret` and `timestamp` are:

Copy

```
key: OElNn5D_Frnf5MR0ChjYdG7PunK0AOgHTvevwzWS
secret： NFqv4MB3hB0SOiEsJNDP9e0jDdKPWbDqS_Z1dbU4
timestamp： 1655896754515
```

The base part of request to query the private stream is

Copy

```
wss://api.pionex.com/ws
```

Step 1, Get current millisecond `timestamp`.

Copy

```
timestamp=1655896754515
```

Step 2, Set query parameters as key-value pairs: `key=value`.

Copy

```
key=OElNn5D_Frnf5MR0ChjYdG7PunK0AOgHTvevwzWS
timestamp=1655896754515
```

Step 3, Sort the key-value pairs in ascending ASCII order by key and concatenate with & .

Copy

```
key=OElNn5D_Frnf5MR0ChjYdG7PunK0AOgHTvevwzWS&timestamp=1655896754515
```

Step 4, Concatenate above result after `PATH` with `?` to generate `PATH_URL.`

Copy

```
/ws?key=OElNn5D_Frnf5MR0ChjYdG7PunK0AOgHTvevwzWS&timestamp=1655896754515
```

Step 5, Concatenate "`websocket_auth`" after above result.

Copy

```
/ws?key=OElNn5D_Frnf5MR0ChjYdG7PunK0AOgHTvevwzWS&timestamp=1655896754515websocket_auth
```

Step 6, Use `API Secret` and the above result to generate `HMAC SHA256` code, then convert it to hexadecimal.

Copy

```
3e901247350e744353f4a7a479fd67181184a627b119352ec1b7a432925e772c
```

Step 7, Assign the hex result to `signature`, add it to query parameter and send request.

Copy

```
wss://ws.pionex.com/ws?key=OElNn5D_Frnf5MR0ChjYdG7PunK0AOgHTvevwzWS&timestamp=1655896754515&signature=3e901247350e744353f4a7a479fd67181184a627b119352ec1b7a432925e772c
```

### Request format

Messages sent to the server should contain the following dictionary items:

* `op`: The operation you want to run. Should be one of

  + `SUBSCRIBE` to subscribe to a topic
  + `UNSUBSCRIBE` to unsubscribe to a topic
* `topic`: The topic for which your want data. Should be one of

  + `TRADE`: for trade market data
  + `DEPTH`: for depth market data
  + `ORDER`: for order account data
  + `FILL`: for fill account data
* `symbol`: The symbol for which you want data. Example: `BTC_USDT`

### Response format

* `topic`
* `symbol`
* `op`: `PING` or `CLOSE`
* `type`: Response of `SUBSCRIBE` and `UNSUBSCRIBE`
* `data`: Subscribed messages
* `timestamp`: The timestamp in millisecond
* `code`: Error code
* `message`: Error message

### Subscribe

Send JSON request to subscribe

Copy

```
{"op": "SUBSCRIBE", "topic": "ORDER", "symbol": "BTC_USDT"}
```

Response

Copy

```
{"type": "SUBSCRIBED", "topic": "ORDER", "symbol": "BTC_USDT"}
```

**Unsubscribe**

Send JSON request to unsubscribe

Copy

```
{"op": "UNSUBSCRIBE", "topic": "ORDER", "symbol": "BTC_USDT"}
```

Response

Copy

```
{"type": "UNSUBSCRIBED", "topic": "ORDER", "symbol": "BTC_USDT"}
```

### HeartBeat

Our server sends '**PING**' heartbeat message every 15 seconds

Copy

```
{"op": "PING", "timestamp": 1566691672311}
```

Client sends '`PONG`' heartbeat message as a reply after receiving '`PING`'. The timestamp of 'PONG' does not need to be consistent with or correspond to '`PING`'.

Copy

```
{"op": "PONG", "timestamp": 1566691672311}
```

Client have to send latest timestamp to keep persistent connection. If the server does not receive a 'PONG' reply after sending 3 'PING' heartbeat, it will close the connection and send the disconnect message to client at the same time.

Copy

```
{"op": "CLOSE", "timestamp": 1566691672311}
```

### Limit

You can create up to 10 connections on the same ip

### Error Code

INVALID\_OP Invalid op.

INVALID\_TOPIC Invalid topic.

INVALID\_SYMBOL Invalid symbol.

PARAMETER\_ERROR Parameter error.

SUBSCRIBED\_TOPICS\_EXCEED\_LIMIT The number of subscribed topics on single connection exceed the limit.

[PreviousGet Klines](https://pionex-doc.gitbook.io/apidocs/restful/markets/get-klines)[NextPublic Stream](https://pionex-doc.gitbook.io/apidocs/websocket/public-stream)

Last updated 1 year ago
