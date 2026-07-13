#!/usr/bin/env python3
"""Lightweight dashboard fixture; no model process required."""
import ast, json, re, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

source = open(sys.argv[1] if len(sys.argv) > 1 else "ds4_server.c", encoding="utf-8").read()
block = source.split("static const char dashboard_html[] =", 1)[1].split("static bool send_dashboard_page", 1)[0]
page = "".join(ast.literal_eval(s) for s in re.findall(r'"(?:[^"\\]|\\.)*"', block)).encode()
base_kv = {"enabled": True, "budget_bytes": 64 << 30, "used_bytes": 46 << 30, "entries": 116, "revision": "1"}
base_calls = {"active_request_id":"99","records":[
    {"request_id":"99","caller":"direct","client":"hanako-agent","api":"responses","status":"active","kind":"chat","stream":True,"tools":True,"started_at":1000.0,"finished_at":0,"prompt_tokens":32768,"cached_tokens":24576,"cache_write_tokens":8192,"output_tokens":814,"cache_source":"disk-text","finish":"","error":"<img src=x>"},
    {"request_id":"98","caller":"192.0.2.7","client":"hermes-agent","api":"openai","status":"failed","kind":"chat","stream":False,"tools":False,"started_at":2000.0,"finished_at":2042.1,"prompt_tokens":39712,"cached_tokens":24576,"cache_write_tokens":4096,"output_tokens":128,"cache_source":"memory","finish":"error","error":"<script>坏</script>"},
    {"request_id":"97","caller":"192.0.2.9","client":"openclaw","api":"anthropic","status":"completed","kind":"completion","stream":True,"tools":False,"started_at":3000.0,"finished_at":3012.5,"prompt_tokens":8192,"cached_tokens":4096,"cache_write_tokens":1024,"output_tokens":512,"cache_source":"disk-text","finish":"stop","error":""},
    {"request_id":"96","caller":"<b>恶意调用方</b>","client":"<img src=x onerror=alert(1)>","api":"openai","status":"failed","kind":"chat","stream":False,"tools":False,"started_at":4000.0,"finished_at":4001.0,"prompt_tokens":8,"cached_tokens":0,"cache_write_tokens":0,"output_tokens":0,"cache_source":"","finish":"error","error":"<script>坏</script>"},
    {"request_id":"95","caller":"198.51.100.12","client":"batch-evaluator","api":"openai","status":"completed","kind":"completion","stream":False,"tools":False,"started_at":5000.0,"finished_at":5008.4,"prompt_tokens":16384,"cached_tokens":12288,"cache_write_tokens":2048,"output_tokens":256,"cache_source":"memory","finish":"stop","error":""}],
    "callers":[{"caller":"direct","client":"hanako-agent","calls":4,"failed":0,"prompt_tokens":90},{"caller":"192.0.2.7","client":"hermes-agent","calls":2,"failed":1,"prompt_tokens":40},{"caller":"192.0.2.9","client":"openclaw","calls":3,"failed":0,"prompt_tokens":22},{"caller":"<b>恶意调用方</b>","client":"<img src=x onerror=alert(1)>","calls":1,"failed":1,"prompt_tokens":8}]}
state = {"kv": dict(base_kv), "admin": [], "status_active": 0, "status_max": 0,
         "status_delay_ms": 0, "admin_delay_ms": 0, "forbidden": False,
         "malformed": False, "mismatch_once": False, "mismatch_remaining": 0, "mismatch_makes_eviction": False,
         "runtime_patch": {}, "dry_runtime_patch": {}, "apply_runtime_patch": {},
         "mismatch_runtime_patch": {}, "mismatch_patch_active": False,
         "context": {"current_tokens":48120,"limit_tokens":163840,"next_limit_tokens":163840,"remaining":115720,"utilization":.2937},
         "context_admin": [], "context_forbidden": False, "context_durable": True, "context_fail_once": False,
         "host_available": True, "offline": False, "calls": dict(base_calls), "status_patch": {}}
lock = threading.Lock()

def status():
    result = {"phase":"decode","active":True,"queue_depth":2,"clients":3,
      "model":{"name":"DeepSeek V4 Flash","backend":"Metal","context_length":163840,"session_pos":48120},
      "request":{"kind":"chat","api":"responses","stream":True,"tools":True,"prompt_tokens":32768,"cached_tokens":24576,"cache_write_tokens":8192,"elapsed_sec":18.4,"cache_source":"disk-text","finish":"","last_error":""},
      "prefill":{"current":8192,"total":8192,"percent":100,"avg_tps":1850.4,"chunk_tps":2011.2,"elapsed_sec":4.4,"eta_sec":0},
      "decode":{"generated":814,"max_tokens":4096,"avg_tps":52.7,"chunk_tps":55.1,"elapsed_sec":14},
      "totals":{"requests":48,"completed":45,"failed":2,"cache":{"prompt_tokens":1264000,"cached_tokens":782000,"prompt_requests":47,"hit_requests":31}},
      "kv_cache":dict(state["kv"]), "context":dict(state["context"]),
      "host":{"available":state["host_available"],"memory_total_bytes":128<<30,"memory_used_bytes":96<<30,"memory_available_bytes":32<<30,"memory_pressure":"warning","swap_total_bytes":16<<30,"swap_used_bytes":2<<30,"process_rss_bytes":12<<30},
      "calls":dict(state["calls"])}
    for key,value in state["status_patch"].items():
        if isinstance(value,dict) and isinstance(result.get(key),dict): result[key]=dict(result[key],**value)
        else: result[key]=value
    return result

def response_runtime(runtime, mode):
    result = dict(runtime)
    patches = [state["mismatch_runtime_patch"] if state["mismatch_patch_active"] else state["runtime_patch"]]
    patches.append(state["apply_runtime_patch"] if mode == "apply" else state["dry_runtime_patch"])
    for patch in patches:
        for key,value in patch.items():
            if value is None: result.pop(key, None)
            else: result[key] = value
    return result

class Handler(BaseHTTPRequestHandler):
    def json(self, value, code=200):
        body=json.dumps(value).encode(); self.send_response(code); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == "/ds4/status":
            with lock:
                state["status_active"] += 1; state["status_max"] = max(state["status_max"], state["status_active"]); delay=state["status_delay_ms"]
            time.sleep(delay/1000)
            if state["offline"]: self.send_error(503); return
            self.json(status())
            with lock: state["status_active"] -= 1
        elif self.path == "/fixture/state": self.json(state)
        else:
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(page))); self.end_headers(); self.wfile.write(page)
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))))
        if self.path == "/fixture/config":
            if body.get("reset"):
                state.update(kv=dict(base_kv), admin=[], status_active=0, status_max=0, status_delay_ms=0, admin_delay_ms=0, forbidden=False, malformed=False, mismatch_once=False, mismatch_remaining=0, mismatch_makes_eviction=False, mismatch_patch_active=False, runtime_patch={}, dry_runtime_patch={}, apply_runtime_patch={}, mismatch_runtime_patch={}, eviction_fail=False, context={"current_tokens":48120,"limit_tokens":163840,"next_limit_tokens":163840,"remaining":115720,"utilization":.2937}, context_admin=[], context_forbidden=False, context_durable=True, context_fail_once=False, host_available=True, offline=False, calls=dict(base_calls), status_patch={})
            if "call_records" in body:
                state["calls"] = dict(state["calls"], records=body["call_records"])
            for key,value in body.items():
                if key != "reset": state[key]=value
            self.json(state); return
        if self.path == "/ds4/admin/context":
            state["context_admin"].append({"value":body.get("context_tokens"),"header":self.headers.get("X-DS4-Admin")})
            if state["context_forbidden"]: self.json({"ok":False,"error":{"message":"fixture context forbidden"}},403); return
            if state["context_fail_once"]:
                state["context_fail_once"] = False
                self.json({"ok":False,"error":{"message":"fixture context failure"}},500); return
            value=body.get("context_tokens")
            if not isinstance(value,int) or value < 1: self.json({"ok":False,"error":{"message":"invalid context"}},400); return
            durable=state["context_durable"]
            state["context"]["next_limit_tokens"]=value
            self.json({"ok":True,"current_context_tokens":state["context"]["limit_tokens"],"next_context_tokens":value,"persistent":{"attempted":True,"committed":True,"durable":durable,"ok":durable}}); return
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
            state["mismatch_patch_active"] = True
            self.json({"ok":False,"runtime":response_runtime(runtime, body["mode"]),"current_revision":kv["revision"],"error":{"code":"kv_state_changed","message":"state changed"}},409); return
        if body["mode"]=="apply" and state.get("eviction_fail"):
            kv.update(used_bytes=40<<30,entries=100,revision=str(int(kv["revision"])+1)); runtime.update(ok=False,applied=False,after_bytes=kv["used_bytes"],after_entries=kv["entries"],revision=kv["revision"])
            self.json({"ok":False,"runtime":response_runtime(runtime, body["mode"]),"error":{"code":"kv_eviction_failed","message":"KV cache eviction failed; the previous limit was restored"}},500); return
        if body["mode"]=="apply":
            kv.update(budget_bytes=new,used_bytes=runtime["after_bytes"],entries=runtime["after_entries"],revision=str(int(kv["revision"])+1)); runtime["revision"]=kv["revision"]
        persistent={"attempted":body["mode"]=="persist","ok":True,"committed":body["mode"]=="persist","durable":body["mode"]=="persist","budget_mb":mb}
        self.json({"ok":True,"runtime":response_runtime(runtime, body["mode"]),"persistent":persistent})
    def log_message(self,*_): pass

ThreadingHTTPServer(("127.0.0.1", int(sys.argv[2]) if len(sys.argv)>2 else 8766), Handler).serve_forever()
