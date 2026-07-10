#!/usr/bin/env python3
"""Lightweight dashboard fixture; no model process required."""
import ast, json, re, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

source = open(sys.argv[1] if len(sys.argv) > 1 else "ds4_server.c", encoding="utf-8").read()
block = source.split("static const char dashboard_html[] =", 1)[1].split("static bool send_dashboard_page", 1)[0]
page = "".join(ast.literal_eval(s) for s in re.findall(r'"(?:[^"\\]|\\.)*"', block)).encode()
base_kv = {"enabled": True, "budget_bytes": 64 << 30, "used_bytes": 46 << 30, "entries": 116, "revision": "1"}
state = {"kv": dict(base_kv), "admin": [], "status_active": 0, "status_max": 0,
         "status_delay_ms": 0, "admin_delay_ms": 0, "forbidden": False,
         "malformed": False, "mismatch_once": False, "mismatch_remaining": 0, "mismatch_makes_eviction": False}
lock = threading.Lock()

def status():
    return {"phase":"decode","active":True,"queue_depth":2,"clients":3,
      "model":{"name":"DeepSeek V4 Flash","backend":"Metal","context_length":163840,"session_pos":48120},
      "request":{"kind":"chat","api":"responses","stream":True,"tools":True,"prompt_tokens":32768,"cached_tokens":24576,"cache_write_tokens":8192,"elapsed_sec":18.4,"cache_source":"disk-text","finish":"","last_error":""},
      "prefill":{"current":8192,"total":8192,"percent":100,"avg_tps":1850.4,"chunk_tps":2011.2,"elapsed_sec":4.4,"eta_sec":0},
      "decode":{"generated":814,"max_tokens":4096,"avg_tps":52.7,"chunk_tps":55.1,"elapsed_sec":14},
      "totals":{"requests":48,"completed":45,"failed":2,"cache":{"prompt_tokens":1264000,"cached_tokens":782000,"prompt_requests":47,"hit_requests":31}},
      "kv_cache":dict(state["kv"])}

class Handler(BaseHTTPRequestHandler):
    def json(self, value, code=200):
        body=json.dumps(value).encode(); self.send_response(code); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == "/ds4/status":
            with lock:
                state["status_active"] += 1; state["status_max"] = max(state["status_max"], state["status_active"]); delay=state["status_delay_ms"]
            time.sleep(delay/1000)
            self.json(status())
            with lock: state["status_active"] -= 1
        elif self.path == "/fixture/state": self.json(state)
        else:
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(page))); self.end_headers(); self.wfile.write(page)
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))))
        if self.path == "/fixture/config":
            if body.get("reset"):
                state.update(kv=dict(base_kv), admin=[], status_active=0, status_max=0, status_delay_ms=0, admin_delay_ms=0, forbidden=False, malformed=False, mismatch_once=False, mismatch_remaining=0, mismatch_makes_eviction=False)
            for key,value in body.items():
                if key != "reset": state[key]=value
            self.json(state); return
        state["admin"].append({"mode":body.get("mode"),"revision":body.get("revision"),"header":self.headers.get("X-DS4-Admin")})
        time.sleep(state["admin_delay_ms"]/1000)
        if state["forbidden"]: self.json({"ok":False,"error":{"code":"forbidden","message":"fixture forbidden"}},403); return
        if state["malformed"]:
            raw=b"{"; self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length","1"); self.end_headers(); self.wfile.write(raw); return
        mb=body["budget_mb"]; new=mb<<20; kv=state["kv"]
        runtime={"attempted":True,"ok":True,"applied":body["mode"]=="apply","old_budget_bytes":kv["budget_bytes"],"new_budget_bytes":new,"before_bytes":kv["used_bytes"],"after_bytes":min(kv["used_bytes"],new),"before_entries":kv["entries"],"after_entries":88 if new<kv["used_bytes"] else kv["entries"],"eviction_required":new<kv["used_bytes"],"revision":kv["revision"]}
        if body["mode"]=="apply" and (state["mismatch_once"] or state["mismatch_remaining"]>0):
            state["mismatch_once"]=False; state["mismatch_remaining"]=max(0,state["mismatch_remaining"]-1); kv["revision"]=str(int(kv["revision"])+1)
            if state["mismatch_makes_eviction"]: kv["used_bytes"]=90<<30; kv["entries"]=150
            self.json({"ok":False,"runtime":runtime,"current_revision":kv["revision"],"error":{"code":"kv_state_changed","message":"state changed"}},409); return
        if body["mode"]=="apply":
            kv.update(budget_bytes=new,used_bytes=runtime["after_bytes"],entries=runtime["after_entries"],revision=str(int(kv["revision"])+1)); runtime["revision"]=kv["revision"]
        persistent={"attempted":body["mode"]=="persist","ok":True,"committed":body["mode"]=="persist","durable":body["mode"]=="persist","budget_mb":mb}
        self.json({"ok":True,"runtime":runtime,"persistent":persistent})
    def log_message(self,*_): pass

ThreadingHTTPServer(("127.0.0.1", int(sys.argv[2]) if len(sys.argv)>2 else 8766), Handler).serve_forever()
