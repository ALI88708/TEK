# TEK — Temporary Environment on Kaggle

Run a full virtual machine inside a free Kaggle notebook session.  
Your local computer acts as a display and input terminal only.

```
 Kaggle (compute)              Your Machine (Windows / Linux / macOS)
 ─────────────────             ───────────────────────────────────────
 QEMU  ──┐                     TEK Controller (desktop app)
 noVNC   ├── AuthProxy ──── Cloudflare Tunnel ──── Fetch descriptor
 TEK     ┘                                          Open display (browser)
```

## Quick start

### 1. TEK Controller (Windows)

```
python -m pip install -e packages/tek-controller
python -m tek_controller
```

Go to **Connection → Generate Secret → Copy**.

### 2. Kaggle Notebook

Open `kaggle/tek_runtime.ipynb` on Kaggle.

Add a secret named `TEK_SESSION_SECRET` *(Add-ons → Secrets → New Secret)*  
with the value copied from the controller.

Run all cells. The notebook will print:

```
host = abc-xyz.trycloudflare.com
pair = ABCDEF
```

### 3. Connect

In the controller:

1. Verify the pair code matches.  
2. Enter the tunnel hostname.  
3. Click **Fetch & Connect**.  
4. Click **Open Display** → noVNC opens in your browser.

## Architecture

| Component | Role |
|-----------|------|
| `packages/tek-runtime/` | Runs on Kaggle: QEMU, auth proxy, tunnel |
| `packages/tek-controller/` | Runs on your machine: UI, fetch, session management |
| `kaggle/tek_runtime.ipynb` | Kaggle notebook entry point |

## Security

- Session secrets are never printed or logged.
- All traffic passes through a HMAC-authenticated proxy.
- Cloudflare tunnel provides TLS; authentication is enforced before any VNC frame is served.

## Any ISO, not just Alpine

TEK treats the ISO as an opaque bootable image. In the Controller open **Start VM**, choose a source
(default test image, direct URL, or a path on Kaggle), set CPU / RAM / disk / BIOS-or-UEFI / machine type,
and press **Generate Kaggle Snippet**. Paste the snippet into the last cell of `kaggle/tek_runtime.ipynb` and run it.
TEK does **not** launch Kaggle notebooks for you.

```python
from tek_runtime import main, GuestConfig, IsoSpec
main(guest=GuestConfig(
    iso=IsoSpec.from_url('https://example.com/os.iso', sha256='<64 hex>', name='My OS'),
    display_name='My OS', vcpu=2, ram_mb=4096, disk_size_gb=10, firmware='uefi', machine='q35',
))
```

* ISO from a URL is downloaded to Kaggle scratch space; SHA-256 is verified when you provide it.
* CPU / RAM / disk requests are checked against the real Kaggle host **before** anything is downloaded.
* A QCOW2 disk is created on request. **Kaggle sessions are temporary: the disk is lost when the session ends.**
  There is no automatic persistence or recovery yet (M2).
* x86_64 only. Kaggle has no KVM, so QEMU runs in software emulation (TCG): expect slow guests.

## Status (read this before trusting it)

Evidence levels: **local** = real QEMU/websockify/AuthProxy/Tk on a Linux dev machine, no mocks;
**Kaggle** = verified in a real Kaggle session.

| Feature | Evidence |
|---------|----------|
| QEMU start / QMP / VNC password / stop (SIGTERM->SIGKILL) | local; **Kaggle: M0 run only for the Alpine start-up** |
| VNC port discovery, QCOW2 disk attach, UEFI (OVMF), q35 | local only |
| AuthProxy: auth before WebSocket upgrade, Origin check, cookie, rate limit | local only |
| VNC data path (QEMU -> websockify -> AuthProxy) | local only |
| Host terminal and live metrics endpoints | local only |
| Controller: fetch descriptor, session cookie, snippet generator, windows | local only (Tk under a virtual display) |
| Cloudflare tunnel, TLS, Windows controller <-> Kaggle | **not verified end to end** |
| Windows / FreeBSD / other guests | **untested** (settings exist, no guest was booted) |
| Display embedded in the Controller | not implemented: noVNC opens in the browser |
| Keyboard / mouse | work inside noVNC in the browser only |
| QCOW2 persistence / recovery (M2) | not implemented |

## Development

```bash
# Run all tests
cd packages/tek-controller && python -m pytest tests/
cd packages/tek-runtime   && python -m pytest tests/

# Build runtime wheel
cd packages/tek-runtime && python -m build
```

## License

MIT
