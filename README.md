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

## Status

| Feature | Status |
|---------|--------|
| QEMU on Kaggle (TCG) | Implemented — awaiting Kaggle M0 test |
| Secure auth proxy | Implemented and unit-tested |
| Cloudflare tunnel | Implemented — awaiting Kaggle network test |
| Controller fetch + connect | Implemented |
| noVNC display (browser) | Implemented via kickoff URL |
| VNC display in controller | Planned (v1) |
| Keyboard / mouse in controller | Planned (v1) |
| QCOW2 session recovery (M2) | Planned |

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
