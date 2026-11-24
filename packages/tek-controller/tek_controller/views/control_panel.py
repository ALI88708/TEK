"""Control Panel — live metrics from Kaggle Runtime Host."""
from __future__ import annotations
import queue, threading, time, tkinter as tk
from collections.abc import Callable
from tek_controller import theme
P = theme.PALETTE

class _Card(tk.Frame):
    def __init__(self, master, label, unit=""):
        super().__init__(master, bg=P["surface"],
                         highlightthickness=1, highlightbackground=P["border"])
        self._unit=unit
        tk.Label(self,text=label,bg=P["surface"],fg=P["muted"],
                 font=theme.fonts().mono_font(7,"bold"),anchor="w").pack(fill="x",padx=10,pady=(8,0))
        self._v=tk.Label(self,text="—",bg=P["surface"],fg=P["text"],
                         font=theme.fonts().mono_font(13,"bold"),anchor="w")
        self._v.pack(fill="x",padx=10,pady=(0,8))
    def set(self,value,*,ok=True):
        txt=f"{value} {self._unit}".strip() if value not in ("—","Unavailable") else value
        self._v.configure(text=txt,fg=P["text"] if ok else P.get("danger","#ff6b6b"))

class ControlPanelView(tk.Frame):
    REFRESH_MS=5000
    def __init__(self,master,*,on_refresh:Callable[[],dict|None]):
        super().__init__(master,bg=P["bg"])
        self._on_refresh=on_refresh
        self._job=None
        self._drain_job=None
        self._results: queue.Queue = queue.Queue()   # worker thread -> Tk thread
        self._build()
    def _build(self):
        self.columnconfigure((0,1,2),weight=1)
        hdr=tk.Frame(self,bg=P["bg"]); hdr.grid(row=0,column=0,columnspan=3,sticky="ew",pady=(0,14))
        tk.Label(hdr,text="KAGGLE RUNTIME — LIVE METRICS",bg=P["bg"],fg=P["muted"],
                 font=theme.fonts().mono_font(8,"bold")).pack(side="left")
        self._ts=tk.Label(hdr,text="",bg=P["bg"],fg=P["muted"],font=theme.fonts().ui_font(8))
        self._ts.pack(side="right")
        tk.Button(hdr,text="Refresh",command=self._do_refresh,bg=P["surface_alt"],fg=P["text"],
                  relief="flat",padx=10,pady=3,font=theme.fonts().ui_font(8)).pack(side="right",padx=(0,8))
        cards_def=[("CPU USAGE","%"),("CPU CORES","vCPU"),("RAM USED","MB"),
                   ("RAM %","%"),("DISK FREE","GB"),("DISK %","%"),
                   ("GPU",""),("QEMU",""),("CONNECTION","")]
        self._cards=[_Card(self,*d) for d in cards_def]
        for i,c in enumerate(self._cards):
            c.grid(row=1+i//3,column=i%3,sticky="nsew",padx=6,pady=6)
        for r in range(1,5): self.rowconfigure(r,weight=1)
        pf=tk.Frame(self,bg=P["surface"],highlightthickness=1,highlightbackground=P["border"])
        pf.grid(row=4,column=0,columnspan=3,sticky="ew",padx=6,pady=(6,0))
        tk.Label(pf,text="PROCESSES",bg=P["surface"],fg=P["muted"],
                 font=theme.fonts().mono_font(7,"bold")).pack(anchor="w",padx=10,pady=(8,2))
        self._procs=tk.Label(pf,text="—",bg=P["surface"],fg=P["text"],
                             font=theme.fonts().mono_font(9),anchor="w",justify="left")
        self._procs.pack(fill="x",padx=10,pady=(0,8))
    def start_polling(self):
        if self._job is not None:           # already polling (e.g. reconnect): keep the single loop
            return
        self._drain()
        self._do_refresh()
    def stop_polling(self):
        for attr in ("_job", "_drain_job"):
            job = getattr(self, attr)
            if job:
                self.after_cancel(job); setattr(self, attr, None)
    def _do_refresh(self):
        def _f():
            try: data=self._on_refresh()
            except Exception: data=None
            self._results.put(data)         # never touch Tk from the worker thread
        threading.Thread(target=_f,daemon=True).start()
        self._job=self.after(self.REFRESH_MS,self._do_refresh)
    def _drain(self):
        try:
            while True: self._update(self._results.get_nowait())
        except queue.Empty: pass
        self._drain_job=self.after(200,self._drain)
    def _update(self,data):
        ts=time.strftime("%H:%M:%S")
        c=self._cards
        if not data:
            self._ts.configure(text=f"Last: {ts} — Unavailable")
            c[8].set("Disconnected",ok=False); return
        self._ts.configure(text=f"Updated: {ts}")
        cpu=data.get("cpu",{}); pct=cpu.get("percent")
        c[0].set(f"{pct:.1f}" if pct is not None else "Unavailable")
        c[1].set(str(cpu.get("count","—")))
        ram=data.get("ram",{}); rp=ram.get("percent")
        c[2].set(str(ram.get("used_mb","—")))
        c[3].set(f"{rp:.1f}" if rp is not None else "—",ok=(rp or 0)<90)
        disk=data.get("disk",{}); dp=disk.get("percent")
        c[4].set(str(disk.get("free_gb","—")))
        c[5].set(f"{dp:.1f}" if dp is not None else "—",ok=(dp or 0)<90)
        gpu=data.get("gpu")
        c[6].set(f"{gpu['name'][:16]} {gpu.get('util_pct','?')}%" if gpu else "Unavailable")
        qemu=data.get("qemu",{}); qok=qemu.get("running",False)
        c[7].set("Running" if qok else "Stopped",ok=qok)
        c[8].set("Connected",ok=True)
        self._procs.configure(text="  ".join(
            f"{'✓' if p['running'] else '✗'} {p['name']}"
            for p in data.get("procs",[])) or "—")
