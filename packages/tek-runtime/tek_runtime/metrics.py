"""Live host metrics — CPU, RAM, Disk, GPU, QEMU status."""
from __future__ import annotations
import os, shutil, time
try:
    import subprocess as _sp
except ImportError:
    _sp = None

def _read(path, default=""): 
    try: return open(path).read()
    except OSError: return default

_prev_cpu: tuple[float,float] | None = None

def cpu_percent() -> float | None:
    global _prev_cpu
    def _times():
        line = _read("/proc/stat","").splitlines()[0]
        vals = [float(x) for x in line.split()[1:]] if line.startswith("cpu") else [0,0,0,0]
        return vals[3]+(vals[4] if len(vals)>4 else 0), sum(vals)
    cur = _times()
    if _prev_cpu is None:
        _prev_cpu = cur; time.sleep(0.2); cur = _times()
    idle_d, tot_d = cur[0]-_prev_cpu[0], cur[1]-_prev_cpu[1]
    _prev_cpu = cur
    return round(100*(1-idle_d/tot_d),1) if tot_d>0 else None

def cpu_count() -> int:
    try: return len(os.sched_getaffinity(0))
    except AttributeError: return os.cpu_count() or 1

def ram_info() -> dict:
    info = {}
    for ln in _read("/proc/meminfo").splitlines():
        for k in ("MemTotal","MemAvailable","MemFree"):
            if ln.startswith(f"{k}:"): info[k] = int(ln.split()[1])*1024
    total=info.get("MemTotal",0); avail=info.get("MemAvailable",info.get("MemFree",0))
    used=total-avail; pct=round(100*used/total,1) if total else 0
    return {"total_mb":total//(1024**2),"available_mb":avail//(1024**2),
            "used_mb":used//(1024**2),"percent":pct}

def disk_info(path="/kaggle/temp") -> dict:
    if not os.path.isdir(path): path="/tmp"
    try:
        u=shutil.disk_usage(path)
        return {"total_gb":round(u.total/(1024**3),1),"used_gb":round(u.used/(1024**3),1),
                "free_gb":round(u.free/(1024**3),1),
                "percent":round(100*u.used/u.total,1) if u.total else 0,"path":path}
    except OSError: return {"path":path}

def gpu_info() -> dict | None:
    if not shutil.which("nvidia-smi"): return None
    try:
        r=_sp.run(["nvidia-smi","--query-gpu=name,utilization.gpu,memory.used,memory.total",
                   "--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=5)
        if r.returncode!=0: return None
        p=[x.strip() for x in r.stdout.strip().split(",")]
        return {"name":p[0],"util_pct":int(p[1]) if len(p)>1 else None,
                "mem_used_mb":int(p[2]) if len(p)>2 else None,
                "mem_total_mb":int(p[3]) if len(p)>3 else None}
    except Exception: return None

def qemu_status() -> dict:
    from . import qemu as _q
    return {"running":_q.is_alive(),"pid":_q.pid()}

def process_list() -> list[dict]:
    procs=[]
    for name in ("qemu-system-x86_64","websockify","cloudflared"):
        try:
            r=_sp.run(["pgrep","-x",name],capture_output=True,text=True)
            procs.append({"name":name,"running":r.returncode==0})
        except Exception:
            procs.append({"name":name,"running":False})
    return procs

def snapshot() -> dict:
    return {"timestamp":time.time(),"cpu":{"percent":cpu_percent(),"count":cpu_count()},
            "ram":ram_info(),"disk":disk_info(),"gpu":gpu_info(),
            "qemu":qemu_status(),"procs":process_list()}
