# TEK Controller

Desktop controller for a temporary TEK environment on Kaggle.

This is the first runnable Controller prototype. The window, navigation, session
state machine, descriptor validation, and local preferences are real. The TEK
Runtime, remote display streaming, and keyboard/mouse forwarding are **not**
implemented in this build, and the UI says so wherever it matters.

## Requirements

- Python 3.11 or newer
- Tk 8.6 (bundled with the official Python installers; on Linux install the
  distribution's Tk package, for example `python3-tk`)

No third-party runtime dependencies.

## Launch

From this directory:

```bash
python -m tek_controller
```

Optional flags:

```bash
python -m tek_controller --view connection
python -m tek_controller --view settings
python -m tek_controller --settings path/to/controller.json
python -m tek_controller --smoke   # open, run the event loop briefly, exit
```

Installing the package also exposes a `tek-controller` script:

```bash
pip install -e .
tek-controller
```

## Tests

```bash
python -m pytest -q
```

The GUI smoke tests need a desktop session; they skip when Tk cannot open a
display.

## Layout

```
tek_controller/
  app.py          window shell, navigation, session actions
  session.py      six-state controller state machine (pure Python)
  descriptor.py   tek/0 descriptor parsing and validation (pure Python)
  settings.py     local preference persistence
  theme.py        monochrome design tokens
  views/          dashboard, connection, settings
  widgets/        reusable primitives, sidebar, display placeholder
```

## Current limitations

- `Create Session` moves through `Preparing`, then stops and reports that no VM
  was created.
- `Connect` validates a pasted descriptor, then reports that the runtime
  integration is not implemented. It never fetches a descriptor or opens a
  viewer.
- The display area is a labelled placeholder. No frames are received.
- Nothing is sent over the network. No credential is stored or logged.
