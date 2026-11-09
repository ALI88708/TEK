# TEK Runtime Bootstrap - Complete Design Review

**Status:** Comprehensive design document for implementation review
**Date:** 2026-10-30
**Scope:** Implementation of the minimal TEK Runtime capable of bootstrapping a temporary Kaggle-side session for Alpine TCG testing.

---

## 1. 11 Core Modules - Detailed Specification

### 1.1 detect.py (Resource Detection)
**Responsibility:** Read container/cgroup CPU, RAM, disk, and GPU resources

**Public Interfaces:**
- `get_cpu_quota() -> dict`: Returns effective_vcpu, quota_us, period_us, nproc, affinity
- `get_ram_limit() -> dict`: Returns effective_gb, limit_bytes, available_kb
- `check_writable_disk(path, min_gb, min_mb_s) -> dict`: Returns free_gb, write_speed_mb_s
- `check_dataset_mount() -> dict`: Returns read_only, read_speed_mb_s
- `check_kvm_available() -> bool`: Returns True if /dev/kvm exists

**Dependencies:**
- os, sys, pathlib, re
- Subprocess calls to read /sys/fs/cgroup, /proc/meminfo, df
- No external Python packages required

**Assumptions:**
- cgroup v2 available on Kaggle containers
- /proc/meminfo accessible
- Standard POSIX filesystem operations

### 1.2 plan.py (Resource Planning)
**Responsibility:** Calculate guest resources and validate against minimums

**Public Interfaces:**
- `calculate_effective_resources(cpu_info, ram_info) -> ResourceInfo`: Core allocation algorithm
- `validate_plan(plan, guest_min_vcpu, guest_min_ram_gb) -> tuple`: Validation with reasons
- `create_resource_plan(requested_plan) -> ResourcePlan`: Main planning function

**Data Structures:**
```python
@dataclass
class ResourceInfo:
    vcpu: int
    ram_mb: int
    disk_gb: float
    # Validation fields
    headroom_vcpu: int = 0
    headroom_ram_mb: int = 0

@dataclass
class ResourcePlan:
    requested: ResourceInfo
    granted: ResourceInfo
    headroom: ResourceInfo
    reasons: List[str]
```

**Dependencies:**
- math module (ceil, min, max)
- detect.py for resource inputs
- No external packages required

**Assumptions:**n- 25% vCPU headroom for system processes
- 2 GB minimum RAM headroom
- User_max parameter from protocol (optional)

### 1.3 deps.py (Dependency Management)
**Responsibility:** Idempotent installation of QEMU, websockify, cloudflared

**Public Interfaces:**
- `ensure_qemu() -> dict`: Installs QEMU, returns status
- `ensure_websockify() -> dict`: Installs websockify, returns status
- `ensure_cloudflared() -> dict`: Installs cloudflared, returns status
- `report_installation_status() -> dict`: Overall dependency status

**Dependencies:**
- subprocess, shlex, tempfile, shutil
- Platform-specific package managers (apt, yum, etc.)
- No external Python packages required

**Assumptions:**
- Standard package managers available in Kaggle
- Network access for package installation
- Sufficient privileges for installation

### 1.4 storage.py (ISO and QCOW2 Management)
**Responsibility:** ISO caching and QCOW2 overlay lifecycle

**Public Interfaces:**
- `ensure_iso_cache(iso_url) -> dict`: Downloads and caches ISO
- `create_overlay(base_path, session_id) -> dict`: Creates QCOW2 overlay
- `export_overlay(overlay_path, export_path) -> dict`: Standalone export
- `verify_qcow2(path) -> dict`: qemu-img check verification

**Dependencies:**
- subprocess, json, hashlib, tempfile, shutil
- qemu-img and qemu-img-convert commands
- No external Python packages required

**Assumptions:**
- qemu-img commands available after deps.py installation
- Write permissions on /kaggle/temp and /kaggle/working
- Network access for ISO downloads

### 1.5 qemu.py (QEMU Orchestration)
**Responsibility:** Build QEMU command and manage guest lifecycle

**Public Interfaces:**
- `build_qemu_command(plan, overlay_path, display_port) -> List[str]`: QEMU command construction
- `start_qemu(command) -> int`: Starts QEMU, returns PID
- `monitor_command(pid, command) -> str`: Sends commands to monitor
- `wait_for_boot(timeout_seconds) -> bool`: Waits for guest boot
- `stop_qemu(pid) -> bool`: Graceful shutdown

**Dependencies:**
- subprocess, threading, queue, time
- qemu.py and storage.py
- No external Python packages required

**Assumptions:**
- QEMU commands available after deps.py installation
- Alpine netboot images available in dataset
- Network connectivity for Alpine boot

### 1.6 session.py (State Machine and Orchestration)
**Responsibility:** Core state machine and session lifecycle management

**Public Interfaces:**
- `SessionModel`: 6-state state machine with transitions
- `SessionOrchestrator`: Module coordination
- `watchdog()`: Periodic QEMU status check (15s intervals)
- `export_session()`: Graceful export and shutdown

**Data Structures:**
```python
class SessionState(StrEnum):
    IDLE = "Idle"
    PREPARING = "Preparing"
    CONNECTING = "Connecting"
    RUNNING = "Running"
    STOPPING = "Stopping"
    FAILED = "Failed"

class SessionModel:
    state: SessionState
    events: List[str]
    transition(target: SessionState, reason: str) -> None
```

**Dependencies:**
- threading, time, json, pathlib
- qemu.py, storage.py, control.py
- No external Python packages required

**Assumptions:**
- Single-threaded session lifecycle
- Atomic state transitions
- Timeout enforcement via threading.Timer

### 1.7 control.py (Descriptor and Status)
**Responsibility:** Session descriptor generation and status reporting

**Public Interfaces:**
- `generate_descriptor(session_id, plan, secret_fingerprint) -> dict`: Descriptor JSON
- `write_descriptor(descriptor, session_dir) -> None`: Writes with mode 0600
- `write_status(status_dict, session_dir) -> None`: Updates status.json
- `serve_descriptor() -> None`: HTTP endpoint for descriptor fetch

**Dependencies:**
- http.server, socketserver, json, base64
- session.py for state info
- cryptography for encoding

**Assumptions:**
- HTTP server can bind to loopback interface
- Secret fingerprint already computed
- Session directory structure established

### 1.8 authproxy.py (Authentication Proxy)
**Responsibility:** Token validation and WebSocket proxying

**Public Interfaces:**
- `setup_authproxy(port, session_manager) -> None`: Starts auth proxy server
- `validate_token(token) -> bool`: Token validation with window
- `serve_viewer() -> None`: Serves noVNC page
- `proxy_websocket() -> None`: Proxies authenticated WebSocket connections

**Dependencies:**
- http.server, websockets, json, base64
- secrets, hashlib
- authproxy-specific for WebSocket handling

**Assumptions:**
- WebSocket library available
- Single-threaded proxy operation
- Token validation efficiency critical

### 1.9 tunnel.py (Cloudflared Tunnel)
**Responsibility:** Quick tunnel management and URL parsing

**Public Interfaces:**
- `start_tunnel() -> dict`: Starts cloudflared, returns URL
- `verify_tunnel(url) -> dict`: Verifies tunnel connectivity
- `get_tunnel_status() -> dict`: Returns tunnel status

**Dependencies:**
- subprocess, json, re, time
- cloudflared binary interface
- No external Python packages required

**Assumptions:**
- cloudflared available after deps.py installation
- Network access for tunnel initialization
- Public DNS resolution for tunnel URL

### 1.10 display.py (Websockify Setup)
**Responsibility:** noVNC WebSocket proxy setup

**Public Interfaces:**
- `setup_websockify(port) -> None`: Configures websockify
- `get_display_status() -> dict`: Returns display status

**Dependencies:**
- subprocess, socket, threading
- websockify command interface
- No external Python packages required

**Assumptions:**
- websockify available after deps.py installation
- Port 6081 available on localhost
- VNC server running in QEMU

### 1.11 main.py (Entry Point)
**Responsibility:** Main orchestration and bootstrap

**Public Interfaces:**
- `main() -> None`: Entry point for Kaggle notebook
- `initialize_session() -> dict`: Session initialization
- `cleanup_session() -> None`: Session cleanup

**Dependencies:**
- All other modules
- Signal handling for graceful shutdown
- Environment variable parsing

**Assumptions:**
- Single session per notebook execution
- Session secret provided via environment
- Root directory permissions for session storage

## 2. Complete Session Lifecycle

### 2.1 State Machine Diagram

```
    +--------+
    |  IDLE  |
    +--------+
       |
       | create session
       v
    +--------+
    |PREPARING| <-- timeout: 15min
    +--------+
       |
       | deps, ISO, overlay
       v
    +--------+
    | BOOTING | <-- timeout: 5min (Alpine)
    +--------+
       |
       | guest ready
       v
    +--------+
    | RUNNING | (QEMU up, display ready)
    +--------+
       |
       | viewer attach
       v
    +--------+
    |CONNECTED| <-- grace period: 5min
    +--------+
       |
       | disconnect
       v
    +--------+
    |DEGRADED| <-- timeout: 5min
    +--------+
       |
       | export
       v
    +--------+
    |EXPORTING| <-- timeout: 20min
    +--------+
       |
       | success
       v
    +--------+
    | ENDED  |
    +--------+
       |
       | failure
       v
    +--------+
    | FAILED |
    +--------+
       |
       | manual reset
       v
    +--------+
    |  IDLE  |
    +--------+

Note: LOST state reachable from any state on container death
```

### 2.2 Valid Transitions

| From State | To State | Condition | Event Source |
|------------|----------|-----------|--------------|
| IDLE | PREPARING | `create_session()` called | Controller |
| IDLE | FAILED | Session reset | Controller |
| PREPARING | IDLE | `abort_unimplemented_create()` | Session timeout |
| PREPARING | BOOTING | Dependencies ready | deps.py |
| PREPARING | FAILED | Preparation timeout | Timeout handler |
| BOOTING | RUNNING | Guest ready | QEMU monitor |
| BOOTING | FAILED | Boot timeout | Timeout handler |
| RUNNING | CONNECTING | Viewer attaches | authproxy.py |
| RUNNING | DEGRADED | Viewer disconnects | authproxy.py |
| CONNECTING | RUNNING | Viewer reconnects | authproxy.py |
| CONNECTING | DEGRADED | Viewer disconnects | authproxy.py |
| DEGRADED | EXPORTING | Grace period timeout | Timeout handler |
| DEGRADED | RUNNING | Viewer reconnects | authproxy.py |
| RUNNING | EXPORTING | `export_session()` called | Controller |
| EXPORTING | ENDED | Export successful | storage.py |
| EXPORTING | FAILED | Export failed | storage.py |
| Any State | LOST | Container death | Watchdog |
| Any State | IDLE | Reset | Controller |

### 2.3 Grace Periods and Timeouts

| State | Grace Period | Timeout | Event |
|-------|-------------|---------|-------|
| PREPARING | 15 minutes | 15 minutes | Abort if deps/ISO/overlay take too long |
| BOOTING | N/A | 5 minutes (Alpine), 30 minutes (Windows PE) | Fail if guest doesn't reach ready |
| CONNECTING | N/A | Viewer attach/connect time | No timeout in this state |
| DEGRADED | 5 minutes | 5 minutes | Time before mandatory export |
| EXPORTING | N/A | 20 minutes | Maximum export duration |

### 2.4 Cleanup Guarantees

1. **Resource Cleanup:** All temporary files deleted on session end
2. **Overlay Preservation:** Overlay never deleted automatically
3. **Export Safeguards:** Atomic rename after verification
4. **State Consistency:** Atomic state transitions prevent partial states
5. **Error Recovery:** Clear error states for manual intervention

## 3. Resource Detection Details

### 3.1 CPU Detection (Measured vs Estimated)

**Measured Values:**
- `nproc`: Actual CPU cores in container (`os.cpu_count()`)
- `affinity`: Actual CPU affinity (`os.sched_getaffinity(0)`)
- `quota_us`: cgroup CPU quota (`/sys/fs/cgroup/cpu.max`)
- `period_us`: cgroup CPU period (`/sys/fs/cgroup/cpu.max`)

**Estimated Values:**
- `effective_vcpu`: Calculated minimum of all above
- `reserve_vcpu`: 25% headroom (estimated)
- `guest_vcpu`: Effective minus reserve (calculated)

### 3.2 RAM Detection (Measured vs Estimated)

**Measured Values:**
- `memory.max`: cgroup RAM limit (`/sys/fs/cgroup/memory.max`)
- `MemAvailable`: Available RAM (`/proc/meminfo`)

**Estimated Values:**
- `effective_ram`: Minimum of limit and available (measured)
- `reserve_ram`: Max(2 GiB, 10% of effective) (estimated)
- `guest_ram`: Effective minus reserve (calculated)

### 3.3 Disk Detection (Measured vs Estimated)

**Measured Values:**
- `free_gb`: Actual free space (`shutil.disk_usage()`)
- `write_speed_mb_s`: Actual write speed (512 MiB write test)
- `read_speed_mb_s`: Actual read speed (512 MiB read test)

**Estimated Values:**
- `headroom_gb`: Safety margin for export (estimated 10%)
- `export_gb`: Expected export size (estimated 1.1x overlay)

### 3.4 Dataset Mount Detection (Measured)

**Measured Values:**
- `read_only`: Mount read-only status (`os.access(path, os.W_OK)`)
- `read_speed_mb_s`: Actual read throughput (100 MiB sequential read)

**Assumptions:**
- Dataset mount is strictly read-only
- Read speed minimum 100 MB/s (provisional)
- No write operations allowed on dataset

## 4. QEMU Execution Strategy

### 4.1 TCG-First Implementation

**KVM Detection:**
- Check `/dev/kvm` existence via `test -e /dev/kvm`
- Fallback to TCG (software emulation) if absent
- Report capability in status

**Alpine Netboot Scope:**
- Target guest OS: Alpine Linux
- Boot method: Network boot via PXE/TFTP
- Duration: ≤ 180s (boot), ≤ 120s (first frame)
- Input latency: ≤ 500ms

### 4.2 Relation to Windows Guest

**Dependency Chain:**
1. M0 measures cgroup limits and disk capacity
2. M0b proves QCOW2 storage with guest virtio
3. M1 boots Alpine successfully (TCG infrastructure)
4. M2 targets Windows PE on same infrastructure
5. M3 targets Windows LTSC (desktop performance)

**Resource Requirements:**
- Windows requires more CPU headroom
- Windows requires larger disk allocation
- Windows requires longer boot timeouts
- Windows requires better network performance

### 4.3 Execution Parameters

**QEMU Command Building:**
- CPU: `-cpu host-mismatch` (TCG compatibility)
- RAM: `-m {guest_ram}mb` (guest allocation)
- Disk: `-drive if=virtio,format=qcow2,file={overlay_path}`
- Network: `-netdev user,id=net0,hostfwd=tcp::2222-:22` (optional)
- Display: `-vnc :5,password={vnc_password},ipv6=off`
- Monitor: `-monitor unix:monitor.sock,server,nowait`

## 5. Bootstrap and Pairing Process

### 5.1 Three-Line Kaggle Startup

```python
# Kaggle notebook cell 1: Import
from tek_runtime import main

# Kaggle notebook cell 2: Configuration (environment variable)
import os
os.environ['TEK_SESSION_SECRET'] = '32_random_bytes_base64url'

# Kaggle notebook cell 3: Start bootstrap
main()
```

### 5.2 Session Creation Flow

1. **Controller generates secret:** 32 random bytes, base64url encoded
2. **Controller derives credentials:** auth token, descriptor token, VNC password, pairing nonce
3. **Runtime reads secret:** From environment variable
4. **Runtime starts QEMU:** With derived VNC password
5. **Runtime starts authproxy:** For authenticated descriptor endpoint
6. **Runtime starts tunnel:** For display and control connectivity
7. **Runtime displays:** Tunnel hostname + pairing nonce
8. **Controller verifies:** Pairing nonce matches derived value
9. **Controller fetches:** Descriptor via authenticated endpoint
10. **Controller validates:** Protocol and secret fingerprint
11. **Controller opens:** Viewer with derived auth token

### 5.3 Authentication Without URL Credential

**URL Treatment:**
- Tunnel hostname: Display only, not a credential
- Pairing nonce: Human verification only, not accepted by endpoints
- Descriptor token: Derived from secret, not in URL
- Auth token: Injected into page JavaScript, not URL

**Authentication Flow:**
1. Controller generates secret and derives all tokens
2. Controller displays only hostname + pairing nonce
3. Controller fetches descriptor with derived token
4. Controller validates fingerprint before connecting
5. Viewer page POSTs derived token, gets cookie
6. WebSocket upgrades after cookie validation

## 6. Security Implementation Details

### 6.1 Token Derivation

```python
import secrets
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf
from base64 import urlsafe_b64encode

class SessionSecret:
    def __init__(self, secret_bytes):
        self.secret = secret_bytes
    
    def derive_auth_token(self, window):
        kdf = hkdf.HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"tek/v0",
            info=f"tek/v0/auth/{window}".encode()
        )
        return urlsafe_b64encode(kdf.derive(self.secret)).decode()
    
    def derive_descriptor_token(self):
        kdf = hkdf.HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"tek/v0",
            info=b"tek/v0/descriptor"
        )
        return urlsafe_b64encode(kdf.derive(self.secret)).decode()
    
    def derive_vnc_password(self):
        kdf = hkdf.HKDF(
            algorithm=hashes.SHA256(),
            length=48,
            salt=b"tek/v0",
            info=b"tek/v0/vnc"
        )
        return urlsafe_b64encode(kdf.derive(self.secret))[:8].decode()
    
    def derive_pairing_nonce(self):
        kdf = hkdf.HKDF(
            algorithm=hashes.SHA256(),
            length=4,
            salt=b"tek/v0",
            info=b"tek/v0/pair"
        )
        return urlsafe_b64encode(kdf.derive(self.secret))[:6].decode()
```

### 6.2 Authentication Proxy Security

**CSRF Protection:**
- No credential-bearing GET endpoints
- POST requires `Content-Type: application/json`
- `SameSite=Strict` cookies
- Origin and `Sec-Fetch-Site` validation

**Token Validation:**
- Constant-time comparison
- 5-15 minute sliding window (±5 minutes skew)
- Immediate invalidation on session end
- HMAC-bound cookies with 15-minute expiry

### 6.3 Secret Handling

**Generation:**
- `secrets.token_bytes(32)` for per-session secret
- Base64url encoding without padding
- Never written to disk or logs
- Stored only in memory

**Lifecycle:**
- Controller: In memory + optional keychain
- Runtime: In memory only
- Both sides: Derive from same secret
- Session end: Immediate invalidation

### 6.4 Display Authentication

**Flow:**
1. Viewer page served by authproxy (not websockify)
2. Controller injects auth token via `evaluate_js`
3. Page POSTs token to `/tek/auth`
4. Proxy validates token, sets HttpOnly cookie
5. noVNC opens WebSocket with cookie
6. Proxy validates cookie before upgrading
7. RFB credentials supplied programmatically

### 6.5 Separation of Concerns

**Runtime Administration vs Guest Control:**
- Administration: QEMU lifecycle, tunnel management, resource planning
- Guest Control: VNC protocol, input simulation, framebuffer updates
- Display: WebSocket proxy (loopback only)
- No public listeners except authproxy

## 7. Storage Management

### 7.1 Capacity Checks

**Pre-flight Calculation:**
```python
def calculate_storage_requirements(iso_size_gb, overlay_reserve_gb=1, export_reserve_gb=1):
    required_gb = iso_size_gb + overlay_reserve_gb + export_reserve_gb + 2  # 2 GB buffer
    return required_gb

def check_disk_capacity(path, required_gb):
    usage = shutil.disk_usage(path)
    free_gb = usage.free / (1024**3)
    return free_gb >= required_gb, free_gb
```

### 7.2 QCOW2 Lifecycle

**Creation:**
```bash
qemu-img create -f qcow2 \
  -b /kaggle/input/dataset/base.qcow2 -F qcow2 \
  /kaggle/temp/tek/{session_id}/overlay.qcow2
```

**Export Process:**
1. **Pre-flight:** `needed = virtual_size × 1.10`
2. **Convert:** `qemu-img convert -O qcow2 -c -o compression_type=zstd overlay.qcow2 .part`
3. **Verify:** `qemu-img check .part`
4. **Hash:** `sha256sum .part`
5. **Promote:** `mv .part /kaggle/working/tek-exports/{session}.qcow2`

### 7.3 Cleanup Behavior

**Overlay Cleanup:**
- Never deleted automatically
- Deleted only after successful export + user action
- Preserved on export failure for retry
- Protected by file permissions (0600)

**Export Failure Handling:**
- Delete temporary `.part` file
- Keep overlay intact
- Report `EXPORT_FAILED` with failing step
- Leave session in `exporting` for retry

## 8. Testing Strategy

### 8.1 Mocked Unit Tests

**Test Infrastructure:**
- pytest framework
- unittest.mock for external dependencies
- Test isolation (no Kaggle dependencies)

**Test Coverage:**
- `test_detect_cpu_quota()`: cgroup file mocking
- `test_detect_ram_limit()`: memory info mocking
- `test_detect_disk_capacity()`: disk usage mocking
- `test_plan_resource_allocation()`: resource calculation testing
- `test_session_state_transitions()`: state machine validation
- `test_authproxy_token_validation()`: token validation testing
- `test_control_descriptor_generation()`: descriptor creation testing

**Assumptions:**
- All external commands mocked
- File system operations mocked
- Network operations mocked
- No real dependencies required

### 8.2 Local Integration Tests

**Test Infrastructure:**
- Separate Python environment
- QEMU binaries mocked (version checks)
- File system operations real
- Network operations limited

**Test Coverage:**
- `test_qemu_command_building()`: Command construction
- `test_storage_overlay_creation()`: QCOW2 operations
- `test_storage_export_protocol()`: Export workflow
- `test_session_lifecycle()`: State machine integration
- `test_authproxy_integration()`: Auth proxy testing

**Assumptions:**
- QEMU binaries available (but not required for all tests)
- File system permissions adequate
- Network access limited to localhost

### 8.3 Real Kaggle Tests

**Not Performed Until:**
- Package deployed to Kaggle
- Measurements completed via constraints notebook
- All M0 measurements obtained

**Test Infrastructure:**
- Kaggle notebook execution
- Real cgroup limits
- Real disk I/O
- Real network connectivity
- Real QEMU execution

**Test Coverage:**
- `test_bootstrap_alpine()`: Full M0 scenario
- `test_resource_detection_real()`: Actual cgroup detection
- `test_qcow2_storage_real()`: Real overlay creation
- `test_export_protocol_real()`: Complete export workflow
- `test_constraints_measurement()`: C1-C13 measurements

## 9. Architecture Compatibility Analysis

### 9.1 docs/architecture.md Alignment

**Section 2.2 - Runtime Components:**
- ✅ All 11 modules match documented responsibilities
- ✅ No base classes in v0 (concrete modules only)
- ✅ Entry point in `main.py`
- ✅ No abstract interfaces until second implementation

**Section 4.1 - Runtime Modules:**
- ✅ `main.py`: Load secret, start session, block until stopped
- ✅ `detect.py`: Read cgroup limits, disk capacity, GPU presence
- ✅ `plan.py`: Turn facts into ResourcePlan with headroom
- ✅ `deps.py`: Install QEMU/websockify/cloudflared
- ✅ `storage.py`: ISO cache, base-image mount, QCOW2 overlay
- ✅ `qemu.py`: Build QEMU command, drive monitor
- ✅ `display.py`: Start websockify on 127.0.0.1:6081
- ✅ `authproxy.py`: Loopback proxy through tunnel
- ✅ `tunnel.py`: Start cloudflared, parse URL
- ✅ `control.py`: Emit descriptor, write status
- ✅ `session.py`: State machine and orchestration

**Section 8.1 - Display Architecture:**
- ✅ VNC on 127.0.0.1:5900
- ✅ websockify on 127.0.0.1:6081
- ✅ authproxy as only tunneled port (127.0.0.1:6080)
- ✅ Controller GPU unused (thin viewer)

**Section 10.1 - Security Factors:**
- ✅ Session auth token: 256-bit HKDF, 5-15 minute window
- ✅ VNC password: 48-bit, second factor only
- ✅ Secret never printed, logged, or URL-borne
- ✅ Descriptor endpoint authentication required

### 9.2 docs/protocol.md Alignment

**Section 3 - Session Secret:**
- ✅ 32 bytes from CSPRNG (`secrets.token_bytes(32)`)
- ✅ Base64url encoding without padding
- ✅ No printing/logging in URLs
- ✅ Derived auth token, descriptor token, VNC password

**Section 4 - Session Descriptor:**
- ✅ All required fields implemented
- ✅ Schema `tek.session.v0`, protocol `tek/0`
- ✅ No secrets in descriptor
- ✅ Authenticated endpoint `/tek/descriptor`

**Section 5 - Pairing:**
- ✅ Controller generates secret and derives credentials
- ✅ Runtime reads secret, displays hostname + nonce
- ✅ Controller verifies nonce and fetches descriptor
- ✅ Controller validates fingerprint and connects

### 9.3 docs/constraints.md Alignment

**Section 2 - Measurement Matrix:**
- ✅ C1: KVM availability (TCG detection)
- ✅ C2: CPU quota (cgroup detection)
- ✅ C3: RAM limit (cgroup detection)
- ✅ C4: Writable disk (capacity and I/O)
- ✅ C5: Dataset mount (read-only check)
- ✅ C6: TCG boot (Alpine netboot)
- ✅ C7: First frame (display readiness)
- ✅ C8: Tunnel (cloudflared verification)
- ✅ C9: Session idle (heartbeat monitoring)
- ✅ C10: Export safeguards (atomic rename)
- ✅ C11: QCOW2 host block layer (benCH)
- ✅ C12: QCOW2 guest virtio (dd test)
- ✅ C13: Storage integrity (pattern + qemu-img check)

**Section 4 - Decision Rules:**
- ✅ All decision rules preserved in design
- ✅ Calibrated thresholds documented
- ✅ Integration dependency chain

## 10. Implementation Phases

### 10.1 Phase 1: Core Infrastructure (Weeks 1-2)

**Deliverables:**
- Complete module structure with `__init__.py` files
- Basic `detect.py` with unit tests
- Basic `plan.py` with unit tests
- Core `session.py` state machine
- Test framework setup

**Dependencies:**
- None (pure Python modules)
- Standard library only

**Acceptance Criteria:**
- All 11 modules created with correct interfaces
- 80% unit test coverage on core functions
- No external dependencies required
- State machine validates all transitions

### 10.2 Phase 2: QEMU and Storage (Weeks 3-4)

**Deliverables:**
- `qemu.py` with command building and lifecycle
- `storage.py` with QCOW2 operations
- `deps.py` with dependency installation
- Integration tests with mocked QEMU

**Dependencies:**
- `detect.py`, `plan.py`, `session.py`
- Basic file system operations
- Subprocess management

**Acceptance Criteria:**
- QEMU command building tested
- QCOW2 overlay creation tested
- Dependency installation tested
- Integration tests pass with mocks

### 10.3 Phase 3: Authentication and Networking (Weeks 5-6)

**Deliverables:**
- `authproxy.py` with token validation
- `tunnel.py` with cloudflared interface
- `control.py` with descriptor serving
- Security unit tests

**Dependencies:**
- All previous phases
- HTTP server capabilities
- WebSocket support

**Acceptance Criteria:**
- Token validation works correctly
- CSRF protection implemented
- Origin/headers validation working
- Security unit tests pass

### 10.4 Phase 4: Orchestration and Integration (Weeks 7-8)

**Deliverables:**
- Complete `main.py` entry point
- Full session lifecycle integration
- Status reporting and monitoring
- M0 constraints measurement

**Dependencies:**
- All previous phases completed
- Real environment for integration
- Kaggle notebook setup

**Acceptance Criteria:**
- Three-line Kaggle startup works
- Full session lifecycle functional
- Status reporting operational
- M0 constraints obtained (tek_constraints.json)

### 10.5 Phase 5: Validation and Documentation (Weeks 9-10)

**Deliverables:**
- E2E testing with real environment
- Complete documentation
- Deployment guides
- Final test coverage report

**Dependencies:**
- All previous phases
- User acceptance testing
- Documentation review

**Acceptance Criteria:**
- All 64 unit/integration tests pass
- M0 constraints fully measured
- Documentation complete
- Ready for Windows PE milestone (M2)

## 11. Design Decisions Requiring Project Owner Approval

### 11.1 Technical Decisions

1. **QEMU Installation Strategy**
   - APT package manager vs. static binary
   - Version pinning vs. latest stable
   - *Impact: Infrastructure dependency, reliability*

2. **Storage Location**
   - `/kaggle/temp/tek/` vs. `/kaggle/working/tek-exports/`
   - Separate overlay vs. combined image
   - *Impact: Backup strategy, disk space management*

3. **Tunnel Provider**
   - cloudflared vs. custom solution
   - HTTPS vs. custom protocol
   - *Impact: Network compatibility, security*

4. **WebSocket Library**
   - Standard library vs. third-party
   - Performance vs. compatibility
   - *Impact: Scalability, maintenance*

### 11.2 Process Decisions

5. **Measurement Thresholds**
   - Boot time: 180s vs. 300s
   - First frame: 120s vs. 180s
   - Export time: 20min vs. 30min
   - *Impact: User experience, milestone scheduling*

6. **Test Strategy**
   - Unit test coverage target (80% vs. 90%)
   - Integration test frequency
   - Staging environment setup
   - *Impact: Quality assurance, release readiness*

7. **Error Handling**
   - Retry strategies (exponential vs. fixed)
   - Fallback mechanisms
   - User notification approach
   - *Impact: Reliability, user experience*

### 11.3 Security Decisions

8. **Token Rotation**
   - 5-minute windows vs. 10-minute windows
   - Skew tolerance (±5 vs. ±10 minutes)
   - *Impact: Security, user experience*

9. **Cookie Security**
   - HttpOnly vs. JavaScript access
   - SameSite Strict vs. Lax
   - *Impact: CSRF protection, functionality*

10. **Logging Redaction**
    - Fields to redact
    - Log level filtering
    - *Impact: Security, debugging*

**Recommendation:** Submit high-risk technical decisions for explicit review before Phase 1 implementation.

---

**Design Review Complete.** This document provides comprehensive technical specifications, architectural mapping, implementation planning, and risk assessment for the TEK Runtime Bootstrap milestone. All requirements from the existing architecture and protocol documentation are preserved while providing clear implementation guidance.

**Next Step:** Project Owner approval of design decisions before implementation begins.