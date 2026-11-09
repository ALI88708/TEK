# TEK Runtime Bootstrap Design

**Status:** Design document for implementation review
**Date:** 2026-10-30
**Scope:** Implementation of the minimal TEK Runtime capable of bootstrapping a temporary Kaggle-side session for Alpine TCG testing.

---

## 1. Purpose

This design documents the minimal TEK Runtime implementation that:

- Detects actual container/cgroup CPU, memory, and writable disk resources
- Checks QEMU availability and reports capability limitations
- Creates and manages isolated temporary session directories
- Starts and monitors a minimal disposable QEMU test VM when environment supports it
- Reports structured session status and errors compatible with TEK architecture
- Supports the three-line Kaggle startup experience

## 2. Verified Repository Facts

From the existing TEK codebase and documentation:

### 2.1 Architecture Structure (docs/architecture.md)

**Runtime components (Kaggle side):**
- `main.py` - Entry point: load session secret, start session, block until stopped
- `detect.py` - Read cgroup CPU/RAM limits, disk capacity, GPU presence
- `plan.py` - Turn facts into ResourcePlan with headroom; refuse unsatisfiable plans
- `deps.py` - Install QEMU/websockify/cloudflared idempotently; report failures
- `storage.py` - ISO cache, base-image mount, QCOW2 overlay, export
- `qemu.py` - Build QEMU command, drive the monitor, stop cleanly
- `display.py` - Start websockify bound to `127.0.0.1:6081`; no public listener
- `authproxy.py` - Loopback proxy exposed only through the tunnel
- `tunnel.py` - Start cloudflared, parse URL, verify it end-to-end
- `control.py` - Emit session descriptor, write status, enforce grace period
- `session.py` - State machine and orchestration

### 2.2 Protocol Constraints (docs/protocol.md)

**Session descriptor (`tek/0`):**
- Required fields: schema, protocol, session_id, created_at, expires_at, runtime_version, secret_fingerprint, display, resources, guest
- No secrets in URLs, notebook output, or logs
- Descriptor served over authenticated endpoint via bearer token
- Session secret: 32 random bytes, base64url encoded, never printed or logged

**Session lifecycle:**
- States: created → preparing → booting → ready → connected → degraded → exporting → ended → lost
- Grace periods: 5 min after disconnect, 15 min in preparing, Alpine 5 min booting, Windows PE 30 min booting
- Keepalive: watchdog thread checks QEMU every 15s, writes status.json

### 2.3 Controller Implementation

Current TEK Controller (packages/tek-controller) shows:
- State machine with 6 states (Idle, Preparing, Connecting, Running, Stopping, Failed)
- SessionModel that manages transitions and events
- Security review completed: descriptor validation rejects malformed URLs without leaking supplied values
- Settings persistence handles missing, corrupt, and inaccessible files safely

### 2.4 Constraints (docs/constraints.md)

**Critical measurements (C1-C13):**
- CPU quota detection from cgroup (v2: cpu.max, v1: quota/period)
- RAM limit detection from cgroup (v2: memory.max, v1: limit_in_bytes)
- Writable disk check with 512 MiB write/read on /kaggle/temp and /kaggle/working
- TCG boot detection: absence of /dev/kvm
- Tunnel verification with cloudflared

## 3. Design Scope and Assumptions

### 3.1 Scope - In

**Core Bootstrap Features:**
1. **Resource Detection**
   - Cgroup CPU quota and effective vCPU calculation
   - Cgroup RAM limit and effective RAM calculation
   - Writable disk capacity and I/O throughput
   - Dataset mount status and throughput

2. **QEMU Orchestration**
   - QEMU TCG boot with Alpine netboot
   - Command-line building with proper resource limits
   - Monitor interaction for guest state tracking
   - Clean shutdown with export capability

3. **Session Management**
   - State machine orchestration
   - Status reporting via status.json
   - Graceful stop with overlay export
   - Keepalive watchdog (15s intervals)

4. **Display Infrastructure**
   - Websockify setup for noVNC
   - Loopback-only binding (127.0.0.1)
   - No public tunneling from this component

5. **Authentication Infrastructure**
   - Session secret handling (32 bytes, base64url)
   - Derived credential generation (auth token, descriptor token, VNC password)
   - Authproxy with token validation
   - Grace period enforcement

### 3.2 Scope - Out

**Not Implemented in Bootstrap:**
- Windows 10 LTSC (M3 milestone)
- Multi-monitor, audio, clipboard, USB support
- GPU passthrough from Kaggle container
- End-to-end encryption beyond tunnel TLS
- Multi-session operation
- Programmatic Kaggle session start
- Authentication beyond session secret derivation

### 3.3 Assumptions

**Verified from Architecture:**
- Kaggle provides cgroup v2 for resource limits
- Alpine netboot is the target for M0
- QCOW2 storage is required before Windows

**Assumptions - To Verify:**
- Qemu-img availability in Kaggle environment
- cloudflared package install capability
- Websockify availability
- Write permissions on /kaggle/temp and /kaggle/working

## 4. Package Structure

### 4.1 Runtime Package Layout

```
TEK/
├── packages/
│   └── tek-runtime/
│       ├── tek_runtime/
│       │   ├── __init__.py                    # Package metadata
│       │   ├── main.py                        # Entry point
│       │   ├── detect.py                      # Resource detection
│       │   ├── plan.py                        # Resource planning
│       │   ├── deps.py                        # Dependency management
│       │   ├── storage.py                     # ISO and QCOW2 management
│       │   ├── qemu.py                        # QEMU orchestration
│       │   ├── display.py                     # Websockify setup
│       │   ├── authproxy.py                   # Authentication proxy
│       │   ├── tunnel.py                      # Cloudflared tunnel
│       │   ├── control.py                     # Descriptor and status
│       │   └── session.py                     # State machine
│       ├── tests/
│       │   ├── test_detect.py
│       │   ├── test_plan.py
│       │   ├── test_qemu.py
│       │   ├── test_session.py
│       │   ├── test_control.py
│       │   └── integration/
│       │       └── test_bootstrap.py
│       └── pyproject.toml
```

### 4.2 Dependencies

**Core Dependencies:**
- Python 3.11+ (runtime requirement)
- cgroup reading (os.sched_getaffinity, /sys/fs/cgroup interfaces)
- QEMU (qemu-img, qemu-system-x86_64)
- websockify (websockify, python-websockify)
- cloudflared (cloudflared package)

**Python Packages:**
- cryptography (for HKDF, base64url)
- pycparser (for cgroup parsing)
- requests (for catalog fetching)
- psutil (optional, for cross-platform resource detection)

## 5. Module Design

### 5.1 detect.py

**Responsibility:** System resource detection

**Key Functions:**
- `get_cpu_quota()`: Returns (effective_vcpu, quota_us, period_us)
- `get_ram_limit()`: Returns (effective_gb, limit_bytes)
- `check_writable_disk(path, min_gb, min_mb_s)`: Returns (free_gb, write_speed_mb_s)
- `check_dataset_mount()`: Returns (read_only, read_speed_mb_s)
- `check_kvm_available()`: Returns boolean

**Output:** Dictionary with all detected values

### 5.2 plan.py

**Responsibility:** Resource allocation and validation

**Key Functions:**
- `calculate_effective_resources(cpu_info, ram_info)`: Returns guest vCPU, RAM
- `validate_plan(plan, guest_min_vcpu, guest_min_ram_gb)`: Returns (is_valid, reason)
- `create_resource_plan(requested_plan)`: Returns ResourcePlan object

**Data Structures:**
```python
@dataclass
class ResourceInfo:
    vcpu: int
    ram_mb: int
    disk_gb: float

@dataclass
class ResourcePlan:
    requested: ResourceInfo
    granted: ResourceInfo
    headroom: ResourceInfo
    reasons: List[str]
```

### 5.3 deps.py

**Responsibility:** Idempotent dependency installation

**Key Functions:**
- `ensure_qemu()`: Installs QEMU if missing
- `ensure_websockify()`: Installs websockify if missing
- `ensure_cloudflared()`: Installs cloudflared if missing
- `report_installation_status()`: Returns status of all dependencies

### 5.4 storage.py

**Responsibility:** ISO cache and QCOW2 overlay management

**Key Functions:**
- `ensure_iso_cache(iso_url)`: Downloads and caches ISO
- `create_overlay(base_path, session_id)`: Creates new QCOW2 overlay
- `export_overlay(overlay_path, export_path)`: Converts overlay to standalone
- `verify_qcow2(path)`: Runs `qemu-img check`

### 5.5 qemu.py

**Responsibility:** QEMU command building and monitor interaction

**Key Functions:**
- `build_qemu_command(plan, overlay_path, display_port)`: Returns command list
- `start_qemu(command)`: Starts QEMU process, returns PID
- `monitor_command(pid, command)`: Sends command to QEMU monitor
- `wait_for_boot(timeout_seconds)`: Waits for guest boot
- `stop_qemu(pid)`: Graceful shutdown

### 5.6 session.py

**Responsibility:** State machine and orchestration

**Key Functions:**
- `SessionModel`: 6-state state machine with transition validation
- `SessionOrchestrator`: Coordinates module execution
- `watchdog()`: Periodic QEMU status check (15s interval)
- `export_session()`: Handles graceful export and shutdown

### 5.7 control.py

**Responsibility:** Descriptor generation and status reporting

**Key Functions:**
- `generate_descriptor(session_id, plan, secret_fingerprint)`: Returns descriptor JSON
- `write_descriptor(descriptor, session_dir)`: Writes with mode 0600
- `write_status(status_dict, session_dir)`: Updates status.json
- `serve_descriptor()`: HTTP endpoint for authenticated descriptor fetch

### 5.8 authproxy.py

**Responsibility:** Authentication proxy with token validation

**Key Functions:**
- `setup_authproxy(port, session_manager)`: Starts the auth proxy server
- `validate_token(token)`: Validates auth token with 5-15 minute window
- `serve_viewer()`: Serves noVNC page
- `proxy_websocket()`: Proxies authenticated WebSocket connections

## 6. Session Lifecycle Implementation

### 6.1 Three-Line Kaggle Startup

```python
# cell in Kaggle notebook
from tek_runtime import main

# Line 1: Import
# Line 2: Configuration (secret from environment)
# Line 3: Start bootstrap
main()
```

### 6.2 State Transitions

1. **created** → **preparing** (M1: constraints measurement)
2. **preparing** → **booting** (M1: deps, ISO, overlay creation)
3. **booting** → **ready** (M1: QEMU booted, display ready, tunnel up)
4. **ready** → **connected** (M1: viewer attaches)
5. **connected** → **degraded** (grace period after disconnect)
6. **degraded** → **exporting** (after grace period timeout)
7. **exporting** → **ended** (successful export)
8. **exporting** → **failed** (export failure)

### 6.3 Grace Period Enforcement

- Disconnect grace period: 5 minutes
- Preparing timeout: 15 minutes
- Booting timeout: 5 minutes (Alpine), 30 minutes (Windows PE)

### 6.4 Export Protocol

1. **Pre-flight space check**: `needed = virtual_size × 1.10`
2. **Convert**: Write to `.part` file
3. **Verify**: `qemu-img check` + hash computation
4. **Atomic promote**: Rename `.part` to final name
5. **Cleanup**: Delete overlay only after successful export

## 7. Resource Detection Implementation

### 7.1 CPU Detection

```python
def get_cpu_quota():
    try:
        # cgroup v2
        with open('/sys/fs/cgroup/cpu.max') as f:
            quota_max = f.read().strip()
            if quota_max == 'max':
                quota_us = 100 * 1_000_000  # unlimited
            else:
                quota_us, period_us = map(int, quota_max.split())
    except FileNotFoundError:
        # cgroup v1 fallback
        with open('/sys/fs/cgroup/cpu/cpu.cfs_quota_us') as f:
            quota_us = int(f.read().strip())
        with open('/sys/fs/cgroup/cpu/cpu.cfs_period_us') as f:
            period_us = int(f.read().strip())
    
    nproc = os.cpu_count() or 1
    affinity = len(os.sched_getaffinity(0))
    effective_vcpu = min(nproc, affinity, ceil(quota_us / period_us))
    return effective_vcpu, quota_us, period_us
```

### 7.2 RAM Detection

```python
def get_ram_limit():
    try:
        with open('/sys/fs/cgroup/memory.max') as f:
            limit_bytes = int(f.read().strip(), 16) if f.read().strip() != 'max' else None
    except FileNotFoundError:
        with open('/sys/fs/cgroup/memory/memory.limit_in_bytes') as f:
            limit_bytes = int(f.read().strip())
    
    with open('/proc/meminfo') as f:
        for line in f:
            if line.startswith('MemAvailable:'):
                available_kb = int(line.split()[1])
                break
        else:
            available_kb = limit_bytes // (1024 * 1024) if limit_bytes else 0
    
    effective_gb = min(limit_bytes // (1024**3) if limit_bytes else 0, available_kb // 1024)
    return effective_gb
```

## 8. Security Implementation

### 8.1 Secret Management

```python
import secrets
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf

class SessionSecret:
    def __init__(self):
        self.secret = secrets.token_bytes(32)
    
    def derive_auth_token(self, window):
        kdf = hkdf.HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"tek/v0",
            info=f"tek/v0/auth/{window}".encode()
        )
        return base64.urlsafe_b64encode(kdf.derive(self.secret)).decode()
    
    def derive_descriptor_token(self):
        kdf = hkdf.HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"tek/v0",
            info=b"tek/v0/descriptor"
        )
        return base64.urlsafe_b64encode(kdf.derive(self.secret)).decode()
```

### 8.2 Authentication Proxy

- Token validation with constant-time comparison
- 5-15 minute window tolerance
- `HttpOnly; Secure; SameSite=Strict` cookies
- Origin and Sec-Fetch-Site CSRF protection
- No credential-bearing GET endpoints

## 9. Testing Strategy

### 9.1 Unit Tests (package/tek_runtime/tests/)

**Mocked Tests (No Kaggle dependencies):**
- `test_detect_cpu_quota()`: Mock cgroup file reading
- `test_detect_ram_limit()`: Mock memory detection
- `test_plan_resource_allocation()`: Mock resource calculations
- `test_qemu_command_building()`: Mock QEMU command construction
- `test_session_transitions()`: Mock state machine behavior
- `test_authproxy_token_validation()`: Mock token validation

**Test Coverage Goals:**
- All core functions tested
- Edge cases covered (zero quotas, no memory limits)
- Error conditions (file not found, permission denied)

### 9.2 Integration Tests (package/tek_runtime/tests/integration/)

**Real Kaggle Verification:**
- `test_bootstrap_alpine()`: Full M0 scenario
- `test_resource_detection()`: Real cgroup detection
- `test_qcow2_storage()`: Real overlay creation and export
- `test_export_protocol()`: Complete export workflow

**Test Environment:**
- Separate Kaggle notebook for integration tests
- Measurement notebook (docs/constraints/tek_constraints.ipynb)
- Automated reporting of C1-C13 measurements

### 9.3 Acceptance Criteria

**M0 (Constraints):**
- All C1-C7 measurements obtained
- `tek_constraints.json` produced
- Every measurement has a value or documented timeout

**M0b (QCOW2 storage):**
- QCOW2 creation and write/read operations
- `qemu-img check` passes after clean shutdown
- Export completes with hash verification
- Storage performance metrics recorded

**M1 (Alpine infra):**
- Boot ≤ 180s, first frame ≤ 120s
- Keystroke visible ≤ 500ms
- Unauthenticated request rejected
- 30 min connected
- Reconnect after 10s network drop

## 10. Failure Handling

### 10.1 Resource Planning Failures

- `RESOURCE_PLAN_UNSATISFIABLE`: Guest minimum vCPU/RAM not met
- `DISK_FULL`: Free space below required reserve
- `DEPS_FAILED`: Package install failures

### 10.2 Session Failures

- `GUEST_BOOT_TIMEOUT`: Guest did not reach ready state
- `TUNNEL_FAILED`: No public URL produced
- `EXPORT_FAILED`: Overlay export failed
- `SESSION_LOST`: Runtime disappeared without ended signal
- `INTERNAL`: Unexpected error

### 10.3 Recovery Actions

- Exponential backoff for retryable errors
- State preservation for manual recovery
- Graceful degradation when possible
- Clean resource cleanup

## 11. Dependencies and Justifications

### 11.1 Runtime Dependencies

| Package | Version | Purpose | Justification |
|---------|---------|---------|---------------|
| Python 3.11+ | >=3.11 | Base runtime | Kaggle notebook requirement |
| cryptography | >=3.4 | HKDF, encoding | Required for session secret derivation |
| pycparser | >=2.21 | Cgroup parsing | Cgroup v1/v2 file parsing |
| psutil | optional | Cross-platform detection | Optional system utilities |

### 11.2 System Dependencies

| Component | Required Version | Purpose | Notes |
|-----------|----------------|---------|-------|
| QEMU | any TCG | VM execution | Must support -cpu host-mismatch |
| websockify | any | VNC over WebSocket | Loopback-only binding |
| cloudflared | any | Quick tunnel | CloudFlared self-hosting |
| qemu-img | any | Image management | QCOW2 operations |

### 11.3 Installation Strategy

**Idempotent installation:**
1. Check if command exists (`which qemu-system-x86_64`)
2. Install via package manager if missing (`apt install qemu-utils`)
3. Verify installation with `--version`
4. Report status for integration tests

## 12. Risks and Mitigation

### 12.1 High-Risk Items

1. **QEMU Availability in Kaggle**
   - **Risk:** Kaggle environment may not have QEMU installed
   - **Mitigation:** Ensure `deps.py` can install QEMU via package manager
   - **Detection:** Pre-flight check in `detect.py`

2. **Disk Space Constraints**
   - **Risk:** Insufficient writable space for overlay + export
   - **Mitigation:** Pre-flight calculation in `storage.py`
   - **Detection:** `check_writable_disk()` with safety margins

3. **Resource Quota Limits**
   - **Risk:** Guest minimum resources not satisfiable
   - **Mitigation:** Fail early with clear error message in `plan.py`
   - **Detection:** `validate_plan()` function

### 12.2 Medium-Risk Items

4. **TCG Performance**
   - **Risk:** Boot times may exceed thresholds
   - **Mitigation:** Measure and calibrate in M0
   - **Detection:** Timing measurements in integration tests

5. **Tunnel Longevity**
   - **Risk:** Quick tunnel may be recycled
   - **Mitigation:** Implement reconnection logic
   - **Detection:** Heartbeat monitoring

### 12.3 Low-Risk Items

6. **Dependency Installation**
   - **Risk:** Package manager failures
   - **Mitigation:** Fallback error reporting
   - **Detection:** Installation status reporting

## 13. Implementation Plan

### 13.1 Phase 1: Core Infrastructure (Week 1-2)

1. Set up package structure
2. Implement `detect.py` with mock tests
3. Implement `plan.py` with unit tests
4. Create basic `session.py` state machine
5. Set up test framework

### 13.2 Phase 2: QEMU and Storage (Week 3-4)

1. Implement `qemu.py` with mock QEMU
2. Implement `storage.py` with test QCOW2
3. Create `deps.py` for dependency management
4. Add integration test infrastructure

### 13.3 Phase 3: Authentication and Networking (Week 5-6)

1. Implement `authproxy.py` with token validation
2. Implement `tunnel.py` with cloudflared interface
3. Implement `control.py` with descriptor serving
4. Add security tests

### 13.4 Phase 4: Orchestration and Integration (Week 7-8)

1. Complete `main.py` entry point
2. Integrate all modules
3. Implement full session lifecycle
4. Run M0 constraints measurement
5. Add E2E tests

### 13.5 Phase 5: Validation and Documentation (Week 9-10)

1. Run all acceptance criteria
2. Document implementation decisions
3. Create deployment guides
4. Finalize test coverage

## 14. Metrics and Monitoring

### 14.1 Runtime Metrics

- Session state transitions
- Resource allocation decisions
- QEMU boot time and first frame
- Export time and integrity verification
- Tunnel connectivity (every 15s)

### 14.2 Health Checks

- Disk space available
- Dependency installation status
- QEMU process health
- Network connectivity
- Memory pressure

### 14.3 Logging

- Structured JSON logs for monitoring
- Redacted sensitive information
- Session lifecycle events
- Error conditions with context
- Performance metrics

---

**Design Review Required:** This implementation plan establishes the foundation for the TEK Runtime Bootstrap milestone. All changes must maintain compatibility with the existing TEK Controller implementation and protocol specifications.