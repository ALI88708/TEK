# TEK — Protocol (v0)

**Status:** Draft for review
**Scope:** v0 session descriptor and pairing; v1 control channel is a draft, not implemented.

---

## 1. Versioning

| Layer | Identifier | Status |
|---|---|---|
| Session descriptor | `tek/0` | Implemented in M1 |
| Control channel | `tek/1` | Draft only |
| Package versions | SemVer (`0.1.0`) | — |

Rules:

- A major protocol mismatch is rejected with `VERSION_MISMATCH`.
- Minor versions add optional fields; unknown fields are ignored.
- The descriptor's `protocol` field is authoritative for the session.

## 2. Roles and trust

- **Runtime** holds the VM, the session secret, the tunnel, and the disk.
- **Controller** holds the same secret, verifies the pairing nonce and fingerprint, and
  drives the viewer.
- **Relay** (v1) is a signaling rendezvous. It never receives the secret, the VNC
  password, or pixels.

The tunnel hostname is unauthenticated to anyone who learns it. It is not a credential.
The secret is the credential.

## 3. Session secret

- 32 random bytes from the OS CSPRNG (`secrets.token_bytes(32)`), generated once per
  session and never reused across sessions.
- Encoding: base64url without padding (43 characters).
- Never printed, never placed in a URL, never written to a log or a status file.
- Stored in memory by both sides; the controller may persist it only in the OS keychain
  for the lifetime of the session.

Derivations:

```
secret = secrets.token_bytes(32)     # per-session CSPRNG output, never reused

# Short-lived display credential.
auth_token(w) = base64url(HKDF-SHA256(
    ikm  = secret,
    salt = b"tek/v0",
    info = b"tek/v0/auth/" + ascii(w),   # w = floor(unix_time / 300)
    L    = 32
))                                   # 43 characters

# One-shot descriptor fetch credential.
descriptor_token = base64url(HKDF-SHA256(secret, b"tek/v0", b"tek/v0/descriptor", L=32))

# Second factor for the RFB handshake, behind the auth proxy.
vnc_password = base64url(HKDF-SHA256(secret, b"tek/v0", b"tek/v0/vnc", L=6))   # 8 chars

# Human-comparable session fingerprint.
fingerprint = SHA256(secret)[0:4].hex()   # 8 hex characters

# Human-visible check that the runtime holds the same secret.
pairing_nonce = base64url(HKDF-SHA256(secret, b"tek/v0", b"tek/v0/pair", L=4))[:6]
```

Rotation and acceptance, precisely:

- `w` is an ASCII decimal integer, no padding, no sign.
- The proxy accepts `w-1`, `w`, and `w+1` measured against the server clock: ±5 minutes
  of skew in either direction.
- A token minted at the end of window `w` dies when `w+1` closes (~5 min). One minted at
  the start of `w` dies at the end of `w+1` (~15 min). The bound is 5–15 minutes.
- No token outlives the session. `ended`, `failed`, or `lost` invalidates every derived
  credential immediately, independent of the window.
- `info` strings are ASCII and domain-separated by purpose; no two purposes share one.
- The pairing nonce is displayed but is **not** accepted by any endpoint. It is a human
  check only, never authentication.

The 8-character VNC password is a VNC protocol constraint and a second layer only; it is
never the authentication boundary (`docs/architecture.md` §10.1).

## 4. Session descriptor (`tek/0`)

The descriptor is **session data, not public output**. It contains no secret and no
password, but it is still treated as sensitive: it is written with mode `0600` and served
only over an authenticated endpoint.

Transport:

- `GET /tek/descriptor` with `Authorization: Bearer <descriptor_token>`.
- `401 AUTH_REQUIRED` without a valid token; `401 AUTH_EXPIRED` outside the window.
- The runtime never writes the descriptor to stdout, stderr, or a world-readable file.
- The notebook displays only the tunnel hostname and a 6-character pairing nonce.

Descriptor body:

```json
{
  "schema": "tek.session.v0",
  "protocol": "tek/0",
  "session_id": "s_01J9Z6K3W7",
  "created_at": "2026-10-30T10:00:00Z",
  "expires_at": "2026-10-30T22:00:00Z",
  "runtime_version": "0.1.0",
  "secret_fingerprint": "9f2c1a7b",
  "display": {
    "transport": "vnc",
    "url": "https://example-words.trycloudflare.com/vnc.html",
    "password_scheme": "hkdf-sha256/v1",
    "geometry": [1280, 800]
  },
  "resources": {
    "vcpu": 3,
    "ram_mb": 24576,
    "disk_gb": 17.5
  },
  "guest": {
    "os": "alpine",
    "state": "ready"
  }
}
```

Field rules:

- `session_id` is random and carries no authority; it is not a credential.
- `display.url` carries no token or password. It grants nothing without the auth token.
- `secret_fingerprint` lets the controller confirm it holds the right secret.
- `resources` reports the granted plan, not the requested one.
- `guest.state` is one of `booting`, `ready`, `stopped`, `failed`.
- `expires_at` is provisional until measurement C9 establishes the real session limit.

The descriptor is fetched once by the controller. A controller that loses it re-fetches
it with the same derived token; the runtime never re-displays it in the notebook.

## 5. Pairing (v0)

### 5.1 Automated flow

1. The controller generates `secret` and derives `fingerprint`, `descriptor_token`,
   `auth_token`, and `pairing_nonce`.
2. The controller writes a private notebook containing `TEK_SESSION_SECRET = "<secret>"`
   in a setup cell and creates it through the Kaggle API. A Kaggle-attached secret is
   preferred when available; embedding is the fallback.
3. The user opens the notebook in Kaggle and runs it.
4. The runtime reads the secret, starts QEMU, the auth proxy, and the tunnel, and writes
   `descriptor.json` with mode `0600`.
5. The runtime displays one line: `host=<tunnel hostname> pair=<nonce>`. No path, no
   query string, no token.
6. The controller verifies that `pair` matches its derived nonce, then fetches
   `https://<host>/tek/descriptor` with `Authorization: Bearer <descriptor_token>`.
7. It validates `protocol` and `secret_fingerprint`, then opens the viewer.
8. The viewer receives `auth_token` at runtime, exchanges it at `/tek/auth` for a
   short-lived cookie, and connects. The VNC password is supplied through the RFB
   credentials API. Neither value enters the URL, the DOM, or the notebook output.

### 5.2 Manual flow

1. The controller shows the secret once in its own UI, with a copy button. It is not a
   URL and is not written to disk.
2. The user pastes it into the notebook's `TEK_SESSION_SECRET` cell and runs it.
3. Steps 4–8 above are identical.

### 5.3 Rejection rules

- `pair` nonce mismatch → abort with `AUTH_FAILED`; the hostname does not belong to this
  session.
- `401` on the descriptor endpoint → `AUTH_FAILED`; retry at most once, then stop.
- Fingerprint mismatch → abort with `AUTH_FAILED`, do not connect.
- Missing secret → the runtime refuses to start; it never generates and prints one.
- Descriptor expired → abort with `AUTH_EXPIRED`.
- Session in `ended`, `failed`, or `lost` → `SESSION_ENDED`. Every derived credential is
  invalid immediately; the proxy clears the cookie, closes listeners, and closes open
  WebSockets.

## 6. Control channel (`tek/1`, draft — not implemented in v0)

The v1 channel is a WebSocket between the controller and a relay, and between the
runtime and the same relay. Both sides dial out; Kaggle never accepts inbound
connections. The relay pairs them by `session_id` and a one-time code.

Envelope:

```json
{
  "v": "tek/1",
  "type": "hello",
  "id": "msg_01J9Z7...",
  "ts": "2026-10-30T10:00:05Z",
  "payload": {}
}
```

Message types:

| Type | Direction | Payload |
|---|---|---|
| `hello` | both | `role`, `session_id`, `fingerprint`, `runtime_version` |
| `welcome` | runtime → controller | `runtime_version`, `capabilities[]`, `limits{}` |
| `plan` | runtime → controller | `vcpu`, `ram_mb`, `disk_gb`, `headroom`, `reasons[]` |
| `status` | runtime → controller | `state`, `guest_state`, `uptime_s`, `display_ready`, `viewers` |
| `heartbeat` | both | `seq` |
| `stop` | controller → runtime | `reason`, `export` (bool) |
| `export_progress` | runtime → controller | `phase`, `bytes_done`, `bytes_total` |
| `bye` | both | `reason` |
| `error` | both | `code`, `message`, `retryable` |

Heartbeat: every 15 s; three missed heartbeats move the peer to `degraded`.

The relay forwards messages; it does not parse payloads beyond routing fields. It does
not hold the secret. Media never goes through the relay in v1; the viewer connects to
the display transport directly.

## 7. Display channel

v0:

1. The viewer loads `display.url` with no credential-bearing query parameters.
2. The controller injects `auth_token` into the page at runtime via `evaluate_js`.
3. The page `POST`s `{"token": "<auth_token>"}` to `/tek/auth`. The proxy requires
   `Content-Type: application/json`, rejects a present `Origin` that is not exactly
   `https://<host>`, rejects `Sec-Fetch-Site: cross-site`, and compares the token in
   constant time.
4. On success it sets `HttpOnly; Secure; SameSite=Strict; Path=/`, HMAC-bound to
   `session_id` and an absolute 15-minute expiry. No credential is returned in the body.
5. noVNC opens `wss://<host>/websockify` with that cookie. The proxy validates the cookie
   **before** sending `101 Switching Protocols`, re-checks `Origin`, and confirms the
   session is still live. A failed check returns `401`/`403`; no upgrade occurs.
6. The proxy forwards the upgraded stream to websockify on `127.0.0.1:6081`.
7. The controller sets `credentials.password` on the RFB object before connecting.
8. The runtime never logs the token, cookie, or password; `authproxy.py` and `display.py`
   redact them.

CSRF posture: no credential-bearing GET exists; `/tek/auth` needs a body token the
attacker does not possess; the cookie is `SameSite=Strict`; `Origin` and `Sec-Fetch-Site`
are checked on both the POST and the upgrade.

VNC (`127.0.0.1:5900`) and websockify (`127.0.0.1:6081`) are loopback-only. The auth
proxy (`127.0.0.1:6080`) is the only tunneled listener.

v1 (WebRTC): DTLS-SRTP protects media end to end; signaling goes through the relay;
TURN is required because quick tunnels do not carry UDP.

## 8. Error codes

| Code | Meaning | Retryable |
|---|---|---|
| `AUTH_REQUIRED` | No token or cookie on a protected endpoint | No |
| `AUTH_EXPIRED` | Token outside its rotation window, or descriptor expired | Yes, re-derive |
| `AUTH_FAILED` | Pairing nonce or fingerprint mismatch, or wrong password | No |
| `SESSION_ENDED` | Session ended, failed, or lost; all credentials invalid | No |
| `FORBIDDEN_ORIGIN` | `Origin` or `Sec-Fetch-Site` check failed on auth or upgrade | No |
| `VERSION_MISMATCH` | Unsupported protocol major | No |
| `RESOURCE_PLAN_UNSATISFIABLE` | Granted plan below guest minimum | No |
| `DISK_FULL` | Free space below required reserve | No |
| `DEPS_FAILED` | Package install failed | Yes |
| `GUEST_BOOT_TIMEOUT` | Guest did not reach ready state | Yes, once |
| `TUNNEL_FAILED` | No public URL produced | Yes, once |
| `EXPORT_FAILED` | Overlay export failed | Yes, if space allows |
| `SESSION_LOST` | Runtime disappeared without `ended` | No |
| `INTERNAL` | Unexpected error | Depends |

## 9. Compatibility

- The controller checks `protocol` before using a descriptor.
- The runtime checks the controller's `hello` version in v1.
- Additive fields are ignored; removals require a major bump.
- The runtime version is reported in the descriptor so the controller can warn about
  known incompatibilities.

## 10. Security properties

Guaranteed by v0:

- No secret, auth token, VNC password, cookie, or full descriptor in the URL, notebook
  output, or logs.
- The descriptor endpoint and the WebSocket both reject unauthenticated requests.
- The WebSocket is validated **before** the protocol upgrade, not after.
- The auth POST and the upgrade enforce `Origin`/`Sec-Fetch-Site` checks (CSRF).
- The controller refuses to connect on a nonce or fingerprint mismatch.
- The pairing nonce is never accepted as authentication by any endpoint.
- Session end invalidates every derived credential immediately.
- The exposed surface is loopback-only except for the tunneled auth proxy.
- A leaked tunnel hostname alone does not grant access; a 256-bit derived token is
  required, and the VNC password is a second layer.

Not guaranteed by v0:

- End-to-end encryption beyond the tunnel's TLS.
- Protection against a compromised Kaggle account or a public notebook.
- Strong authentication from the VNC password alone: 8 characters by protocol limit.
- Replay protection at the RFB layer; the 5–15 minute token window is the only bound.
- Protection against a malicious actor who already holds the session secret.
- Protection against a compromised local machine that can read the injected token.

v1 replaces the VNC password as the primary factor with a relay-issued, short-lived
token and an auth proxy in front of the display.

