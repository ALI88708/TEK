# TEK — Kaggle Constraints

**Status:** measurement plan and results log
**Rule:** no number in this document is a constant until it has a dated measurement.

---

## 1. Verified vs. assumed

**Verified from a primary source**

- The documented Kaggle CLI surface is batch-oriented: `kernels push`, `kernels status`,
  `kernels output`. It does not expose a live control stream. (Kaggle API repository.)

**Reported by the community or the user, not yet verified**

- CPU notebook: 4 vCPUs, up to ~30 GiB RAM (the user's screenshot shows `Max 30GiB`).
- `/kaggle/working`: ~20 GB.
- Dataset size: ~20 GB per dataset; a separate private-dataset quota is reported.
- Session duration: commonly cited 9–12 h depending on accelerator; idle behavior unclear.
- `/dev/kvm`: absent; QEMU falls back to TCG.

**Unknown until measured**

- Actual cgroup CPU quota and memory limit in a CPU notebook.
- Actual free space on `/kaggle/temp` vs. `/kaggle/working`.
- Whether `/kaggle/input` is strictly read-only and how fast it reads.
- Whether background processes survive after a cell returns.
- How long an idle session survives.
- Whether a quick tunnel stays reachable for 60+ minutes.
- Alpine TCG boot time and first-frame time on the real host.
- QCOW2 block-layer throughput and virtio-blk throughput under TCG.
- Whether a clean guest shutdown leaves a QCOW2 image that passes `qemu-img check`.

## 2. Measurement matrix

| ID | Measurement | Method | Pass threshold | If it fails |
|---|---|---|---|---|
| C1 | KVM availability | `test -e /dev/kvm` | Absent (expected) | Redesign around TCG; report |
| C2 | CPU quota | cgroup v2 `cpu.max` / v1 quota vs. `nproc` | Detected value within ±5% | Fix detection before M1 |
| C3 | RAM limit | `memory.max` / `MemAvailable` | Detected within ±5% | Fix detection before M1 |
| C4 | Writable disk | `df` + 512 MiB write/read on `/kaggle/temp` and `/kaggle/working` | ≥ 15 GiB free on temp; ≥ 100 MB/s write (provisional) | Choose a smaller base image; adjust overlay location |
| C5 | Dataset mount | List `/kaggle/input`, write probe, read throughput | Read-only = true; read ≥ 100 MB/s (provisional) | Change base-image strategy |
| C6 | TCG boot | Alpine netboot to `login:` | ≤ 180 s | Tune QEMU; consider a lighter guest |
| C7 | First frame | QEMU `screendump` non-blank | ≤ 120 s | Tune display; measure again |
| C8 | Tunnel | cloudflared + self-fetch ×5 | 5/5 HTTP 200; ≤ 2 s each | Try `--protocol http2`; consider an alternative |
| C9 | Session idle | Heartbeat log every 30 s for 60 min | ≥ 60 min alive | Document the limit; design keepalive |
| C10 | Export safeguards | Backed overlay → `.part` → `qemu-img check` → SHA-256 → atomic rename; verify the overlay is unchanged | Space check passes; check clean; hash recorded; overlay preserved; no backing file | Adjust export strategy; never delete the overlay |
| C11 | QCOW2 host block layer | `qemu-img bench`: sequential 1 MiB write/read, 4 KiB write/read | Numbers recorded; no I/O errors | Try `cache=none`; record the difference |
| C12 | QCOW2 guest virtio | Alpine netboot + `rdinit=/bin/sh` + `-drive if=virtio`; timed `dd` inside the guest | Write and read complete; numbers recorded | Mark inconclusive; do not guess |
| C13 | Storage integrity | Write a random 8 MiB pattern at offset 8 MiB, read it back, compare hashes; `qemu-img check` after guest shutdown | Hashes match; check reports 0 errors | Treat as a blocker for M2 |

C10–C13 form **M0b**. They measure the QEMU block layer, virtio, and the export path,
not a Windows filesystem. C12 numbers must never be presented as Windows storage
performance.

**Separation rule.** C11 (host block layer) and C12 (guest virtio) are reported separately
and are never averaged or combined into one "storage score". They measure different
layers, and a number from one cannot stand in for the other.

**Integrity limit.** `qemu-img check` validates QCOW2 metadata consistency: refcounts,
leaked clusters, and internal structures. It does **not** prove that guest data is
correct, that the guest filesystem is consistent, or that data reached durable storage
before a crash or power loss. A clean check is necessary, not sufficient. C13 therefore
also compares a written pattern read back from the guest disk; that is the data-level
check, and it too covers only a clean shutdown, not an arbitrary crash.

Thresholds marked *provisional* are calibrated by the first real M0/M0b run, not by
assumption.

## 3. How to run

1. Create a Kaggle notebook: Python, CPU, **Internet ON**.
2. Import `tools/constraints/tek_constraints.ipynb`.
3. Run cells in order: environment + dependencies, disk/dataset I/O, TCG boot, tunnel and
   heartbeat, then the three QCOW2 storage cells (block layer, guest virtio, export).
4. Note the tunnel hostname printed by the tunnel cell and open it from another device.
5. Leave the notebook **idle for 60 minutes**. Do not stop it.
6. Run the report cell. It writes `/kaggle/working/tek_constraints.json`.
7. If the session died, reopen the notebook and run the report cell again; the heartbeat
   log shows the last timestamp before the kill.
8. Paste the JSON back for analysis.

The notebook uses no secrets. The tunnel serves a blank test page.

## 4. Decision rules

- **Disk (C4/C5).** If free writable space cannot hold a compressed Windows base image
  plus a growing overlay plus an export, the LTSC path is not viable. Fallback: a
  lightweight Linux desktop, or a smaller Windows image with a documented limitation.
- **TCG (C6/C7).** If Alpine needs more than 180 s to a login prompt, Windows will be
  much worse. Do not start the Windows milestones until the boot path is tuned.
- **Session (C9).** If the session dies while idle before 60 minutes, TEK needs a
  keepalive strategy or an explicit "session may end" warning. Measure before promising
  long work sessions.
- **Tunnel (C8).** If quick tunnels are recycled or blocked, test a named tunnel or an
  alternative transport before building the controller around it.
- **Dataset (C5).** If `/kaggle/input` is slow or size-limited, prefer a smaller base and
  a separate state dataset.
- **Storage (C11–C13).** If the integrity check fails, M2 does not start. A failed
  `qemu-img check` after a clean guest shutdown is a blocker, not a tuning issue. If C12
  is merely slow, recalibrate the M2 thresholds; if it is inconclusive, say so and rerun
  before deciding.
- **Export (C10).** If a 1 GiB overlay takes longer than the export budget or the
  destination cannot hold the standalone image, reduce the overlay size or move the
  export target; never delete the overlay to make room.

## 5. Open questions

1. Does an interactive Kaggle session survive with no cell execution for 60+ minutes?
2. Do background processes survive after the cell returns, or only while the kernel is
   executing?
3. Is the reported 30 GiB RAM the cgroup limit, or is less available to user processes?
4. Is `/kaggle/temp` on the same filesystem as `/kaggle/working`, and does it survive a
   stop?
5. What is the real private-dataset quota, and can a 10–15 GB QCOW2 be uploaded and
   mounted reliably?
6. Does cloudflared QUIC work, or is HTTP/2 required?
7. How does QEMU TCG scale with 3 vs. 4 guest vCPUs on this host?

## 6. Results log

Append one entry per run. Do not overwrite old entries.

```
### YYYY-MM-DD — <Kaggle notebook URL or ID>

- Host: <CPU model>, <nproc> vCPU, <RAM> GiB
- KVM: <present/absent>
- cgroup CPU: <effective vCPU> (source: <v2/v1/nproc>)
- cgroup RAM: <effective GiB> (limit: <value>)
- Disk: /kaggle/temp <free> GiB, /kaggle/working <free> GiB
- Disk I/O: write <MB/s>, read <MB/s>
- Dataset: read-only <yes/no>, read <MB/s>
- TCG boot: login <s>, first frame <s>
- Storage host bench: seq write <MB/s>, seq read <MB/s>, 4k write <µs/op>, 4k read <µs/op>
- Storage guest virtio: write <MB/s>, read <MB/s>, status <ok/inconclusive>
- Storage integrity: pattern <match/mismatch>, qemu-img check <errors>
- Export: 1 GiB convert <s>, hash <match/mismatch>, check <errors>
- Tunnel: <protocol>, self-fetch <n/5>, max <s>
- Session: heartbeats <n>, last <timestamp>, gaps > 90 s <n>
- Notes:
```

