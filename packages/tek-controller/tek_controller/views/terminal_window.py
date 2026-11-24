"""Interactive terminal — WebSocket to Kaggle Runtime bash."""
from __future__ import annotations
import queue, ssl, threading, tkinter as tk
from tkinter import scrolledtext
from tek_controller import theme
P = theme.PALETTE
try:
    import websocket as _ws
    _WS_AVAILABLE = True
except ImportError:
    _WS_AVAILABLE = False

class TerminalWindow(tk.Toplevel):
    def __init__(self,master,*,tunnel_host:str,session_cookie:str,url:str|None=None):
        super().__init__(master)
        self.title("TEK — Kaggle Runtime Terminal"); self.geometry("900x560")
        self.configure(bg=P["bg"]); self.protocol("WM_DELETE_WINDOW",self._close)
        self._host=tunnel_host; self._cookie=session_cookie; self._url=url
        self._ws=None; self._q:queue.Queue[str]=queue.Queue(); self._done=False
        self._hist:list[str]=[]; self._hidx=-1
        self._build(); self._connect()
    def _build(self):
        hdr=tk.Frame(self,bg=P["panel"],height=38); hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr,text="KAGGLE RUNTIME — TERMINAL",bg=P["panel"],fg=P["muted"],
                 font=theme.fonts().mono_font(8,"bold")).pack(side="left",padx=12)
        self._st=tk.Label(hdr,text="Connecting…",bg=P["panel"],fg=P["muted"],
                          font=theme.fonts().ui_font(8)); self._st.pack(side="right",padx=12)
        tk.Button(hdr,text="Disconnect",command=self._disconnect,bg=P["surface_alt"],fg=P["text"],
                  relief="flat",padx=8,pady=2,font=theme.fonts().ui_font(8)).pack(side="right",padx=(0,8))
        self._out=scrolledtext.ScrolledText(self,bg="#0d1117",fg="#c9d1d9",
                                            insertbackground="#c9d1d9",font=("Courier New",10),
                                            relief="flat",bd=0,padx=10,pady=10,state="disabled")
        self._out.pack(fill="both",expand=True)
        bot=tk.Frame(self,bg=P["panel"],height=38); bot.pack(fill="x",side="bottom"); bot.pack_propagate(False)
        tk.Label(bot,text="$ ",bg=P["panel"],fg="#58a6ff",
                 font=("Courier New",10,"bold")).pack(side="left",padx=(10,0))
        self._inp=tk.Entry(bot,bg="#0d1117",fg="#c9d1d9",insertbackground="#c9d1d9",
                           relief="flat",font=("Courier New",10)); self._inp.pack(side="left",fill="x",expand=True,ipady=6)
        self._inp.bind("<Return>",self._send); self._inp.bind("<Up>",self._hprev)
        self._inp.bind("<Down>",self._hnext); self._inp.focus_set()
        tk.Button(bot,text="Send",command=self._send,bg=P["surface_alt"],fg=P["text"],
                  relief="flat",padx=10,pady=2,font=theme.fonts().ui_font(8)).pack(side="right",padx=(0,8))
        self._poll()
    def _connect(self):
        if not _WS_AVAILABLE:
            self._append("[ERROR] Install websocket-client: pip install websocket-client\n")
            self._st.configure(text="Missing: websocket-client",fg=P.get("danger","#ff6b6b")); return
        ctx=ssl.create_default_context(); ctx.set_alpn_protocols(["http/1.1"])
        # Worker-thread callbacks ONLY put items on a queue; the Tk thread (_poll) applies them.
        # (str = terminal output, tuple = ("status", text, ok))
        self._ws=_ws.WebSocketApp(self._url or f"wss://{self._host}/tek/terminal",
            header={"Cookie":f"tek_session={self._cookie}"},
            on_open=lambda ws:(self._q.put("[Connected]\n"), self._q.put(("status","Connected",True))),
            on_message=lambda ws,m:self._q.put(m if isinstance(m,str) else bytes(m).decode(errors="replace")),
            on_error=lambda ws,e:(self._q.put(f"\n[Error: {e}]\n"), self._q.put(("status","Error",False))),
            on_close=lambda ws,c,m:(None if self._done else (self._q.put(f"\n[Closed]\n"), self._q.put(("status","Disconnected",False)))))
        # `origin=` (not a header) so the library sends exactly ONE Origin, matching the tunnel host.
        threading.Thread(target=self._ws.run_forever,
                         kwargs={"sslopt":{"context":ctx},"origin":f"https://{self._host}"},
                         daemon=True).start()
    def _send(self,event=None):
        cmd=self._inp.get()
        if not cmd.strip(): return
        self._hist.append(cmd); self._hidx=len(self._hist); self._inp.delete(0,"end")
        self._append(f"$ {cmd}\n")
        if self._ws:
            try: self._ws.send(cmd+"\n")
            except Exception as e: self._append(f"[SEND ERROR] {e}\n")
    def _disconnect(self):
        if self._ws: self._ws.close()
        self._st.configure(text="Disconnected",fg=P["muted"])
    def _poll(self):
        try:
            while True:
                item=self._q.get_nowait()
                if isinstance(item,tuple):
                    _,text,ok=item
                    self._st.configure(text=text,fg=P["text"] if ok else P.get("danger","#ff6b6b"))
                else:
                    self._append(item)
        except queue.Empty: pass
        if not self._done: self.after(100,self._poll)
    def _append(self,text):
        self._out.configure(state="normal"); self._out.insert("end",text)
        self._out.see("end"); self._out.configure(state="disabled")
    def _hprev(self,e=None):
        if self._hist and self._hidx>0:
            self._hidx-=1; self._inp.delete(0,"end"); self._inp.insert(0,self._hist[self._hidx])
    def _hnext(self,e=None):
        if self._hidx<len(self._hist)-1:
            self._hidx+=1; self._inp.delete(0,"end"); self._inp.insert(0,self._hist[self._hidx])
        else: self._hidx=len(self._hist); self._inp.delete(0,"end")
    def _close(self):
        self._done=True; self._disconnect(); self.destroy()
