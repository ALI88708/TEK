"""VNC window — separate Toplevel for Guest VM display (browser-based v0)."""
from __future__ import annotations
import tkinter as tk, webbrowser
from typing import Callable
from tek_controller import theme
P = theme.PALETTE

class VncWindow(tk.Toplevel):
    def __init__(self,master,*,tunnel_host:str,kickoff_url:str,
                 on_disconnect:Callable[[],None]|None=None):
        super().__init__(master)
        self.title("TEK — Guest VM Display"); self.geometry("780x480")
        self.configure(bg=P["bg"]); self.protocol("WM_DELETE_WINDOW",self._on_close)
        self._host=tunnel_host; self._kickoff=kickoff_url
        self._on_disconnect=on_disconnect; self._build(); self.after(400,self._open)
    def _build(self):
        hdr=tk.Frame(self,bg=P["panel"],height=38); hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr,text="GUEST VM — VNC DISPLAY",bg=P["panel"],fg=P["muted"],
                 font=theme.fonts().mono_font(8,"bold")).pack(side="left",padx=12)
        self._st=tk.Label(hdr,text="Waiting…",bg=P["panel"],fg=P["muted"],
                          font=theme.fonts().ui_font(8)); self._st.pack(side="right",padx=12)
        body=tk.Frame(self,bg=P["bg"]); body.pack(fill="both",expand=True,padx=24,pady=20)
        tk.Label(body,text="GUEST VM DISPLAY",bg=P["bg"],fg=P["text"],
                 font=theme.fonts().ui_font(16,"bold")).pack(pady=(20,8))
        tk.Label(body,text=(
            "Display is served via noVNC in your browser.\n"
            "Click Open Display to view the guest OS — keyboard and mouse work inside the browser.\n"
            "Closing this window does NOT stop the guest VM."),
            bg=P["bg"],fg=P["muted"],font=theme.fonts().ui_font(9),
            justify="center",wraplength=600).pack(pady=(0,20))
        for lbl,val in [("HOST",self._host),("DISPLAY","noVNC (browser)"),
                        ("AUTH","Session cookie (HttpOnly)")]:
            r=tk.Frame(body,bg=P["surface_alt"]); r.pack(fill="x",pady=2)
            tk.Label(r,text=lbl,bg=P["surface_alt"],fg=P["muted"],
                     font=theme.fonts().mono_font(7,"bold"),width=10,anchor="w").pack(side="left",padx=10)
            tk.Label(r,text=val,bg=P["surface_alt"],fg=P["text"],
                     font=theme.fonts().mono_font(9),anchor="w").pack(side="left")
        btns=tk.Frame(body,bg=P["bg"]); btns.pack(pady=16)
        self._btn=tk.Button(btns,text="Open Display in Browser",command=self._open,
                            bg=P.get("accent","#1a73e8"),fg="white",relief="flat",
                            padx=20,pady=8,font=theme.fonts().ui_font(10,"bold")); self._btn.pack(side="left",padx=4)
        tk.Button(btns,text="Copy URL",command=self._copy,bg=P["surface_alt"],fg=P["text"],
                  relief="flat",padx=12,pady=8,font=theme.fonts().ui_font(9)).pack(side="left",padx=4)
        tk.Label(body,text="v1 (planned): embedded VNC viewer with direct input capture.",
                 bg=P["bg"],fg=P["dim"],font=theme.fonts().ui_font(8)).pack()
    def _open(self):
        try:
            webbrowser.open(self._kickoff)
            self._st.configure(text="Opened in browser",fg=P["text"])
            self._btn.configure(text="Reopen Display")
        except Exception as e:
            self._st.configure(text=f"Error: {e}",fg=P.get("danger","#ff6b6b"))
    def _copy(self):
        self.clipboard_clear(); self.clipboard_append(self._kickoff)
        self._st.configure(text="URL copied",fg=P["text"])
    def _on_close(self):
        if self._on_disconnect: self._on_disconnect()
        self.destroy()
