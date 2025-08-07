# Rate Limit

#### `/api/` Limit Introduction

* Each route has a `weight` which determines for the number of requests each endpoint counts for. Heavier endpoints will have a heavier `weight`.
* According to the two modes of IP and Account limit, each are independent.
* All endpoints share the 10 per second limit based on IP.
* Private endpoints share the 10 per second limit based on ACCOUNT.
* When the `weight` of your requests exceed limit, you will receive HTTP status 429 and your IP/ACCOUNT will be banned (60 seconds).
* Repeatedly violating rate limits or failing to back off after receiving 429s will extend the time of IP/ACCOUNT ban, extend 10 seconds per request.

[PreviousBasic Info](https://pionex-doc.gitbook.io/apidocs/restful/general/basic)[NextAuthentication](https://pionex-doc.gitbook.io/apidocs/restful/general/authentication)

Last updated 3 years ago
