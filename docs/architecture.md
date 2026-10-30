# TEK — Architecture (v0)

**Status:** Draft for review
**Date:** 2026-10-30
**Scope:** v0 prototype. This document does not describe the full product.

---

## 1. Purpose

TEK (Temporary Environment on Kaggle) runs a temporary virtual machine inside a Kaggle
notebook and exposes it to a desktop controller on the user's computer. The VM's CPU,
RAM, and disk live in Kaggle. The local computer receives the screen and sends
keyboard/mouse input. The VM is disposable by default, with an explicit export path.

TEK is not a permanent remote desktop, not a local hypervisor, and not a way to move
Kaggle compute outside Kaggle.

## 2. Invariants

These hold for every milestone. A change to one of them is an architecture change, not
an implementation detail.

- **I1 — Compute locality.** VM execution, RAM, and disk stay in Kaggle. The local
  machine is a thin client: display and input only.
- **I2 — No hardcoded resources.** CPU, RAM, and writable disk are derived from the
  actual cgroup/container limits at runtime. No `4`, `30 GB`, or `20 GB` constants.
- **I3 — No ISO redistribution.** The repository contains catalog metadata, never ISO
  binaries. Users provide legally obtained media.
- **I4 — No secrets in URLs or output.** VNC passwords, session secrets, auth tokens,
  and the full descriptor never appear in a URL, in ordinary notebook output, or in
  logs. Only the tunnel hostname and a non-credential pairing nonce are displayed.
- **I5 — Ephemeral by default, export explicit.** A disposable overlay is the default.
  Persistence happens only through an explicit export/recovery flow, and the user is
  told when it did not happen.
- **I6 — Alpine is not a Windows proof.** The Alpine milestone proves infrastructure
  (QEMU TCG, display, input, tunnel, lifecycle). It says nothing about Windows 10 LTSC
  performance. Windows PE is a separate milestone; LTSC is a third.
- **I7 — No speculative abstractions.** v0 uses concrete modules. Provider interfaces
  (`Hypervisor`, `DisplayTransport`, `Tunnel`, `ControlChannel`) are introduced only
  when a second implementation exists.
- **I8 — Session auth is independent of transport.** A 256-bit, short-lived token
  derived from the session secret gates the display endpoint. The tunnel hostname is
  never treated as a credential, and the VNC password is never the authentication
  boundary.

## 3. System overview

```
┌──────────────────────────────┐        ┌────────────────────────────────────────┐
│ TEK Controller (local)       │        │ TEK Runtime (Kaggle notebook)          │
│                              │        │                                        │
│  GUI (pywebview)             │        │  session.py ──► qemu.py ──► guest VM   │
│  Kaggle API client           │        │       │            │                   │
│  noVNC viewer (embedded)     │        │       │            └─ QCOW2 overlay   │
│  local hardware detection    │        │       ├─ display.py (websockify+noVNC) │
└──────────────┬───────────────┘        │       ├─ tunnel.py  (cloudflared)      │
               │                        │       └─ control.py (descriptor)       │
               │  HTTPS/WSS (media)     └──────────────────┬─────────────────────┘
               └────────────► Cloudflare edge ◄────────────┘
```

Two planes:

- **Control plane.** v0 is a manual pairing: the notebook displays only the tunnel
  hostname and a non-credential pairing nonce derived from the secret; the controller
  holds the secret,
  fetches the descriptor over an authenticated endpoint, and derives the auth token and
  VNC password. v1 adds a relay for automatic pairing.
- **Media plane.** v0 is noVNC over WebSocket to a Cloudflare quick tunnel. Pixels and
  input travel on this plane; the control plane never carries them.

## 4. Components

### 4.1 Runtime (Kaggle side)

Entry point: a thin notebook cell imports `tek_runtime` and calls `main()`.

| Module | Responsibility |
|---|---|
| `main.py` | Load the session secret, start the session, block until stopped. |
| `detect.py` | Read cgroup CPU/RAM limits, disk capacity, GPU presence. |
| `plan.py` | Turn facts into a `ResourcePlan` with headroom; refuse unsatisfiable plans. |
| `deps.py` | Install QEMU/websockify/cloudflared idempotently; report failures. |
| `storage.py` | ISO cache, base-image mount, QCOW2 overlay, export. |
| `qemu.py` | Build the QEMU command, drive the monitor, stop cleanly. |
| `display.py` | Start websockify bound to `127.0.0.1:6081`; no public listener. |
| `authproxy.py` | Loopback proxy exposed only through the tunnel: token check, cookie issue, descriptor endpoint, WebSocket gate. |
| `tunnel.py` | Start cloudflared, parse the URL, verify it end-to-end. |
| `control.py` | Emit the session descriptor, write status, enforce the grace period. |
| `session.py` | State machine and orchestration. |

No base classes in v0. Each module is concrete and testable in isolation.

### 4.2 Controller (local side)

| Module | Responsibility |
|---|---|
| `app.py` | pywebview window; local UI. |
| `detect.py` | OS, architecture, decoder capabilities (informational in v0). |
| `kaggle_api.py` | Create/update the private notebook; download exports later. |
| `session.py` | Generate the secret, derive the auth token and password, fetch the descriptor, connect. |
| `viewer/` | Embedded noVNC; injects the token at runtime, sets RFB credentials programmatically. |
| `ui/` | Session form, status, export controls. |

The controller never imports runtime code. It speaks only the protocol.

### 4.3 Catalog (separate repository)

`tek-catalog` holds `isos.json` plus a JSON Schema. CI validates the schema, URL shape,
and hash format. It never holds binaries. TEK fetches the catalog over HTTPS, caches it,
and verifies each ISO against its SHA-256 when a hash is present. A user-supplied direct
URL is a first-class path: download, hash, show the hash, require confirmation when the
catalog had no expected value.

### 4.4 Protocol (shared package)

Pure data and version rules, no I/O: session descriptor, secret derivation, control
message schemas (v1 draft), error codes. See `docs/protocol.md`.

## 5. v0 scope

**In scope**

- Alpine boot under QEMU TCG as an infrastructure test.
- Resource detection from cgroups and writable disk probes.
- noVNC display and keyboard/mouse input.
- Cloudflare quick tunnel.
- Secure pairing: controller-held secret, derived short-lived auth token, derived VNC
  password, descriptor served only over an authenticated endpoint.
- QCOW2 storage test (M0b) before any Windows work.
- Graceful stop with an explicit overlay export.
- The constraints notebook (`tools/constraints/tek_constraints.ipynb`).

**Out of scope for v0**

- Windows 10 LTSC as a supported guest (M3, separate milestone).
- WebRTC, relay-based control, audio, clipboard, USB, multi-monitor.
- GPU passthrough (not possible from a Kaggle container).
- Multi-session or multi-user operation.
- Programmatic Kaggle session start (v0 starts the notebook in the Kaggle UI).

## 6. Session lifecycle

States:

`created → preparing → booting → ready → connected → (degraded) → exporting → ended`

`lost` is reachable from any state when the controller loses the runtime without an
`ended` signal.

| State | Meaning | Timeout / rule |
|---|---|---|
| `created` | Notebook started; secret loaded. | — |
| `preparing` | Installing deps, fetching ISO, creating overlay. | 15 min |
| `booting` | QEMU started; waiting for the guest. | Alpine 5 min; Windows PE 30 min (provisional) |
| `ready` | Display and tunnel are up; descriptor served. | — |
| `connected` | A viewer is attached. | v0: QEMU monitor shows a VNC client |
| `degraded` | Viewer detached. | 5 min grace period, then export and stop |
| `exporting` | Merging the overlay to an export file. | 20 min |
| `ended` | QEMU stopped, tunnel closed, summary written. | — |
| `lost` | No `ended` signal; the container likely died. | No export guaranteed |

**Keepalive.** The notebook cell blocks on `session.wait()` so the kernel stays active.
A watchdog thread checks QEMU every 15 s and writes `status.json` to `/kaggle/working`.
v0 does not auto-restart a dead QEMU; it reports and stops, to avoid crash loops.

**Disconnect rule.** A viewer disconnect starts the grace timer. Reconnecting cancels it.
The overlay is never deleted before an export attempt or an explicit discard.

**Data-loss rule.** A hard container death can still lose the overlay. The controller
marks the session `lost` and says so explicitly; it never reports success. Optional
periodic exports are a user choice, not a default.

## 7. Resource planning

Inputs, all read at runtime:

- **CPU:** `os.sched_getaffinity(0)`, `/sys/fs/cgroup/cpu.max` (v2),
  `cpu.cfs_quota_us` + `cpu.cfs_period_us` (v1).
- **RAM:** `/sys/fs/cgroup/memory.max` (v2), `memory.limit_in_bytes` (v1),
  `MemAvailable` from `/proc/meminfo`.
- **Disk:** `shutil.disk_usage()` plus a writable probe on `/kaggle/temp` and
  `/kaggle/working`.
- **GPU:** `nvidia-smi` presence. Informational only; the guest cannot use it.

Derivation:

```
effective_vcpu = min(nproc, ceil(quota / period), affinity)
reserve_vcpu   = max(1, ceil(effective_vcpu * 0.25))
guest_vcpu     = max(1, effective_vcpu - reserve_vcpu)

effective_ram  = min(cgroup_limit, MemAvailable)
reserve_ram    = max(2 GiB, 10% of effective_ram)
guest_ram      = min(effective_ram - reserve_ram, user_max)
```

Defaults: on a 4-vCPU container the guest gets 3 vCPUs. 4 is allowed only with an
explicit warning. The guest never receives 100% of RAM.

`ResourcePlan` records requested, granted, and the reason for any reduction. If the
granted plan is below the guest minimum, the runtime refuses to start and reports why.

Disk requirement before boot:

```
required = iso_size + overlay_reserve + export_reserve + 2 GiB
```

If `required` exceeds free writable space, the runtime refuses to start.

## 8. Storage and persistence

Layout:

```
/kaggle/input/<dataset>/base.qcow2          read-only base image (private dataset)
/kaggle/temp/tek/<session>/overlay.qcow2    disposable overlay
/kaggle/temp/tek/<session>/iso/             ISO cache
/kaggle/working/tek-exports/<session>.qcow2 explicit export target
```

Overlay creation:

```
qemu-img create -f qcow2 \
  -b /kaggle/input/<dataset>/base.qcow2 -F qcow2 \
  /kaggle/temp/tek/<session>/overlay.qcow2
```

The base is never modified. The overlay grows with guest writes; free space is checked
before and during the session.

**Export on graceful stop:**

```
qemu-img convert -O qcow2 -c -o compression_type=zstd \
  overlay.qcow2 /kaggle/working/tek-exports/<session>.qcow2
sha256sum /kaggle/working/tek-exports/<session>.qcow2
```

This merges the backing file into a standalone image. There is no incremental export in
v0.

**Export safeguards (mandatory order):**

1. **Pre-flight space check.** Compute `needed = virtual_size × 1.10` (standalone
   conversion cannot be smaller than the used clusters plus metadata) and compare it with
   the free space on the destination filesystem *while the overlay still exists*. If
   `needed > free`, stop and report `DISK_FULL` with both numbers. Do not start the
   conversion.
2. **Convert.** Write to `<session>.qcow2.part`, never to the final name.
3. **Structural verification.** `qemu-img check` must report zero errors; `qemu-img info`
   must report the expected virtual size and no backing file.
4. **Content verification.** Compute SHA-256 of the `.part` file and record it in the
   session summary and `status.json`.
5. **Atomic promote.** Rename `.part` to the final name only after steps 3 and 4 pass.
6. **Never touch the overlay before success.** The overlay is deleted only after a
   successful promote *and* an explicit user action, never automatically.
7. **Failure path.** If any step fails, delete the `.part` file only, keep the overlay,
   emit `EXPORT_FAILED` with the failing step, and leave the session in `exporting` so
   the user can retry or discard deliberately.

The runtime never reports `ended` with a successful export unless steps 3–5 passed.

**What `qemu-img check` proves.** It verifies QCOW2 metadata consistency: refcounts,
cluster leaks, and internal structures. It does **not** prove that guest data is correct,
that the guest filesystem is consistent, or that data reached durable storage before a
crash or power loss. A clean check is necessary, not sufficient. The integrity claim in
M0b is limited to "the pattern read back matched and the image structure was consistent
after a clean guest shutdown".

**Recovery:**

1. Controller downloads the export with `kaggle kernels output` after the kernel stops,
   or the user downloads it from the notebook UI.
2. The user publishes it as a new private dataset version.
3. The next session mounts that version as the base and creates a fresh overlay.
4. No automatic merge. The user chooses which base to boot.

**Limitations (to be measured in M0):** `/kaggle/working` capacity, private dataset
quota, upload/download time, export time, and the fact that a hard container death
produces no export at all.

## 9. Display architecture

**v0 — VNC.**

- QEMU exposes VNC on `127.0.0.1:5900` with a password.
- `websockify` serves noVNC on `127.0.0.1:6081`. It is never tunneled directly.
- `authproxy.py` is the only tunneled port (`127.0.0.1:6080`). It serves the viewer page,
  issues the session cookie, and proxies the WebSocket to `6081` after authentication.
- VNC sends framebuffer updates (Tight/ZRLE). There is no video codec, no H.264, and no
  hardware video decoding. **The local GPU is unused in v0.** It is a thin viewer, not a
  decoder.
- Keyboard and mouse are VNC events on the same WebSocket, behind the same auth gate.

**v1 — WebRTC.** H.264/VP9 with browser hardware decode is the reason local GPU
detection exists. It needs TURN/UDP, because Cloudflare quick tunnels carry HTTP and
WebSocket only. It is not part of v0.

**Guest GPU.** None. A Kaggle container cannot pass its GPU through to a guest. The
runtime detects the GPU for reporting only; the guest renders in software.

## 10. Security

**Threat model.** Tunnel hostname leakage; notebook output leakage; an observer at the
tunnel provider; a compromised local machine; a compromised Kaggle account; an
unauthenticated scanner that guesses or learns a tunnel hostname.

### 10.1 Two independent factors

| Factor | Entropy | Lifetime | Protects |
|---|---|---|---|
| Session auth token | 256-bit, HKDF-SHA256 | 5-minute window, ±1 accepted (5–15 min validity) | Viewer page, descriptor, WebSocket |
| VNC password | ~48-bit (8 chars, protocol limit) | Session | The RFB handshake behind the proxy |

The VNC password is **not** the authentication boundary. A request without a valid auth
token never reaches websockify or QEMU. The 8-character password is a second, weaker
layer that exists because RFB requires one.

The pairing nonce is neither factor. It is a human check only: no endpoint accepts it as
authentication.

### 10.2 Derivation

```
secret = secrets.token_bytes(32)        # per-session CSPRNG output; never reused

auth_token(w) = base64url(HKDF-SHA256(
    ikm  = secret,
    salt = b"tek/v0",
    info = b"tek/v0/auth/" + ascii(w),  # w = floor(unix_time / 300), decimal, no padding
    L    = 32
))                                      # 43 chars

descriptor_token = base64url(HKDF-SHA256(secret, b"tek/v0", b"tek/v0/descriptor", L=32))
vnc_password     = base64url(HKDF-SHA256(secret, b"tek/v0", b"tek/v0/vnc", L=6))
pairing_nonce    = base64url(HKDF-SHA256(secret, b"tek/v0", b"tek/v0/pair", L=4))[:6]
fingerprint      = SHA256(secret)[0:4].hex()
```

Rules:

- Every `info` value is ASCII and domain-separated by purpose. No two purposes share one.
- `w` is an ASCII decimal integer with no padding and no sign.
- The proxy accepts `w-1`, `w`, and `w+1` against the server clock, tolerating ±5 minutes
  of skew in either direction.
- Validity is therefore 5 to 15 minutes: a token minted at the end of window `w` expires
  when `w+1` closes (~5 min); one minted at the start of `w` lasts until `w+2` (~15 min).
- The runtime transmits no token. Both sides derive it from the secret.
- Session end is authoritative: `ended`, `failed`, or `lost` invalidates every derived
  credential immediately, regardless of window.

### 10.3 Descriptor handling

The descriptor is session data, not public output.

- The runtime writes `descriptor.json` with mode `0600` under the session directory.
- It is served only by `GET /tek/descriptor`, which requires
  `Authorization: Bearer <descriptor_token>` and a live session.
- The notebook displays **one line**: the tunnel hostname and the 6-character pairing
  nonce. Neither is a credential; without the secret the endpoint returns `401`.
- The nonce is never accepted by any endpoint. It only lets a human confirm that the
  runtime holds the same secret.
- The controller fetches the descriptor over the tunnel, validates `protocol`, and only
  then opens the viewer.
- Logs redact `Authorization`, cookies, `Sec-WebSocket-Protocol`, and any `token` field.

The tunnel hostname is the one routing datum that must be displayed, because v0 has no
relay and Kaggle exposes no live output API. It grants nothing on its own.

### 10.4 Display authentication

1. The viewer page is served by `authproxy.py`, not by websockify.
2. The controller injects the derived token into the page at runtime through
   `evaluate_js` — not into the URL, the DOM, or the page source.
3. The page `POST`s the token to `/tek/auth`. The proxy:
   - requires `Content-Type: application/json`;
   - rejects a present `Origin` that is not exactly `https://<host>` (`403`);
   - rejects `Sec-Fetch-Site: cross-site` when present (`403`);
   - compares the token in constant time;
   - sets `HttpOnly; Secure; SameSite=Strict; Path=/`, HMAC-bound to `session_id` and an
     absolute 15-minute expiry.
4. noVNC opens `wss://<host>/websockify` with that cookie. The proxy validates the cookie
   **before** sending `101 Switching Protocols`, re-checks `Origin`, and confirms the
   bound session is still live. Failure returns `401`/`403` and never upgrades.
5. QEMU VNC stays on `127.0.0.1:5900`; websockify stays on `127.0.0.1:6081`. Only the
   proxy is tunneled.

CSRF posture: no credential-bearing GET; the auth POST requires a body token the attacker
does not have; the cookie is `SameSite=Strict`; `Origin` and `Sec-Fetch-Site` are checked.

### 10.5 Limitations

- Cloudflare terminates TLS. There is no end-to-end encryption; an observer at the edge
  can read the token in transit.
- An 8-character VNC password is about 48 bits. It is a second layer, not a boundary.
- A private notebook still stores the secret in Kaggle's notebook source.
- A compromised Kaggle account or a public notebook defeats the model.
- No replay protection at the RFB layer. The 5–15 minute token window is the only replay
  bound, and only for tokens that already leaked.
- The tunnel hostname is displayed, so assume an observer of the notebook UI knows it.
  Authentication never depends on it.
- A cookie outlives a network drop but not the session: reconnects need a fresh token,
  and session end clears the cookie and closes listeners.

v1 replaces the derived token with a relay-issued single-use token and moves the auth
proxy to the edge.

## 11. Milestones and acceptance criteria

| Milestone | Proves | Does not prove | Exit criteria |
|---|---|---|---|
| **M0 — Constraints** | Kaggle limits, TCG boot, tunnel, session lifetime | Anything about Windows | `tek_constraints.json` produced; every measurement has a value or a documented timeout |
| **M0b — QCOW2 storage** | Virtio-blk + QCOW2 read/write under TCG, integrity, export cost | Windows storage performance | Sequential and 4K numbers recorded; pattern read-back matches; `qemu-img check` clean after shutdown; a standalone export completes, hashes, and leaves the overlay untouched |
| **M1 — Alpine infra** | QEMU TCG, resource detection, display, input, auth, export | Windows performance | Boot ≤ 180 s; first frame ≤ 120 s; keystroke visible ≤ 500 ms; unauthenticated request rejected; 30 min connected; reconnect after a 10 s network drop; export hash matches |
| **M2 — Windows PE** | Windows boot path under TCG | LTSC desktop usability | PE reaches its shell ≤ 30 min (provisional, calibrated by M0/M0b); input works; 30 min stable |
| **M3 — Windows LTSC** | A prebuilt LTSC base image | General Windows performance | Boot from base ≤ 10 min (provisional); input latency ≤ 200 ms (provisional); export/restore cycle works |

Thresholds marked *provisional* are calibrated by M0 and M0b. Alpine success is never
used as evidence for Windows performance. M2 does not start until M0b reports clean
storage results.

## 12. Risks and open questions

- **Disk budget vs. a Windows image.** If writable space cannot hold a usable base plus
  overlay plus export, the LTSC path is not viable. Fallback: a lighter Linux desktop.
- **TCG performance.** Windows 10 is the worst-case guest. Measure before promising.
- **Session idle timeout.** If Kaggle stops an idle notebook while the user is only
  interacting through the tunnel, the product needs a keepalive or a documented limit.
- **Tunnel longevity.** Quick tunnels may be recycled; measure over 60+ minutes.
- **Dataset limits.** Private dataset size and quota determine the base-image strategy.
- **Account/ToS risk.** An open-source release multiplies it. Document it; do not hide it.
- **Catalog legality.** Metadata only; users supply media.

## 13. Repository layout (v0)

```
TEK/
├── docs/{architecture,protocol,constraints}.md
├── packages/
│   ├── tek-protocol/tek_protocol/{messages,version}.py
│   ├── tek-runtime/tek_runtime/{main,detect,plan,deps,storage,qemu,display,authproxy,tunnel,control,session}.py
│   └── tek-controller/tek_controller/{app,detect,kaggle_api,session}.py
│       └── viewer/ + ui/
├── notebook/tek.ipynb                  # thin bootstrap (M1)
├── tools/constraints/tek_constraints.ipynb
├── catalog/                            # schema + pointer to tek-catalog
├── tests/{unit,contract,e2e}/
└── .github/workflows/
```

The top-level split is unchanged from the approved structure. The internal provider
interfaces from the first proposal are deferred until a second implementation exists.

## 14. Requirements traceability

| Requirement | Where it is addressed |
|---|---|
| Alpine is infrastructure only; Windows PE separate | I6, §5, §11 |
| Explicit overlay export/recovery | I5, §6, §8 |
| Export safeguards: space check, verify, never delete overlay | §8, `docs/constraints.md` C10 |
| cgroup/container-based resource planning | I2, §7 |
| No secrets in URLs or notebook output | I4, §10, `docs/protocol.md` §3–5 |
| Independent session auth layer | I8, §4.1, §9, §10.1–10.4, `docs/protocol.md` §3, §7 |
| CSRF protection and pre-upgrade validation | §10.4, `docs/protocol.md` §7 |
| Session end invalidates credentials | §10.2, §10.5, `docs/protocol.md` §5.3, §8 |
| HKDF context and rotation rules | §10.2, `docs/protocol.md` §3 |
| Pairing nonce is not authentication | §10.1, §10.3, `docs/protocol.md` §3 |
| `qemu-img check` is not crash proof | §8, `docs/constraints.md` C13 |
| Host vs. guest storage kept separate | `docs/constraints.md` C11, C12 |
| Descriptor treated as secret | I4, §10.3, `docs/protocol.md` §4 |
| Session lifecycle and no silent loss | §6, §8 |
| VNC vs. hardware decoding separated | §9 |
| Measurable acceptance criteria | §11, `docs/constraints.md` |
| QCOW2 storage test before Windows PE | §11 (M0b), `docs/constraints.md` C10–C13 |


