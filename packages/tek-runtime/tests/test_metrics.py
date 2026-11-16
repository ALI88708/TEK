"""Unit tests for metrics.py."""
import sys
sys.path.insert(0,str(__import__("pathlib").Path(__file__).parent.parent.parent))
from tek_runtime.metrics import cpu_count,ram_info,disk_info,gpu_info,snapshot

def test_cpu_count_positive():     assert cpu_count()>=1
def test_ram_total_positive():     assert ram_info()["total_mb"]>0
def test_ram_percent_range():      r=ram_info(); assert 0<=r["percent"]<=100
def test_disk_fallback():          d=disk_info("/nonexistent"); assert d["path"]=="/tmp"
def test_disk_free_positive():     assert disk_info("/tmp")["free_gb"]>0
def test_gpu_none_or_dict():       r=gpu_info(); assert r is None or isinstance(r,dict)
def test_snapshot_keys():
    s=snapshot()
    for k in("timestamp","cpu","ram","disk","qemu","procs"): assert k in s
def test_snapshot_no_secrets():
    dump=str(snapshot()).lower()
    for w in("password","token","secret"): assert w not in dump
def test_cpu_percent_range():
    from tek_runtime.metrics import cpu_percent
    r=cpu_percent()
    assert r is None or 0<=r<=100
