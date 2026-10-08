"""Live dashboard for photos_to_prompts.py. Run: python dashboard.py (opens http://127.0.0.1:8765).
Read-only, localhost only. Reads <output folder>/_progress.json that the captioner keeps updated."""
import io, json, os, threading, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from PIL import Image
from photos_to_prompts import CFG, OUT_DIR, load_system, load_image, EXTS

STATUS = os.path.join(OUT_DIR, "_progress.json")
PORT = int(CFG.get("dashboard_port", 8765))

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prompt Run</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1c1b19;--mute:#6f6c66;--line:#e3e0d9;--acc:#b4532a;--ok:#2f7d4f;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#161513;--card:#201f1c;--ink:#efece6;--mute:#9a968d;--line:#35332e;--acc:#e08a5f;--ok:#6cc08b;--bad:#f0877f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 48px}h1{font-size:20px;margin:0 0 4px}.sub{color:var(--mute);margin-bottom:16px}
.grid{display:grid;grid-template-columns:minmax(0,340px) minmax(0,1fr);gap:16px}@media(max-width:760px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.card h2{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--mute);margin:0 0 10px}
.photo{width:100%;aspect-ratio:4/5;object-fit:contain;background:var(--bg);border-radius:8px;display:block}
.bar{height:14px;background:var(--bg);border-radius:7px;overflow:hidden;border:1px solid var(--line)}.bar>div{height:100%;background:var(--acc);width:0;transition:width .4s}
.stats{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:10px;color:var(--mute)}.stats b{color:var(--ink)}
.row{display:flex;flex-direction:column;gap:16px}
pre{white-space:pre-wrap;word-break:break-word;margin:0;font:13px/1.5 ui-monospace,Consolas,monospace;max-height:340px;overflow:auto}
details summary{cursor:pointer;color:var(--acc);font-weight:600}
.pill{display:inline-block;padding:1px 8px;border-radius:99px;border:1px solid var(--line);font-size:12px}.ok{color:var(--ok)}.bad{color:var(--bad)}
ul{list-style:none;margin:0;padding:0}li{padding:3px 0;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:8px}li:first-child{border:0}
</style></head><body><main>
<h1>Photo → prompt</h1><div class="sub" id="sub">waiting for a run…</div>
<div class="grid">
 <div class="card"><h2>Converting now</h2><img id="img" class="photo" alt=""><div id="file" style="margin-top:8px;word-break:break-all"></div></div>
 <div class="row">
  <div class="card"><h2>Progress</h2><div class="bar"><div id="fill"></div></div><div class="stats" id="stats"></div></div>
  <div class="card"><h2>Model</h2><div id="model">–</div><details style="margin-top:10px"><summary>System prompt</summary><pre id="sys"></pre></details></div>
  <div class="card"><h2>Newest prompt written</h2><pre id="last">–</pre></div>
  <div class="card"><h2>Recent results</h2><ul id="recent"></ul></div>
 </div></div></main>
<script>
const $=id=>document.getElementById(id);let shown="",sysDone=false;
const esc=s=>String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;");
const f=s=>{s=Math.max(0,s|0);const h=s/3600|0,m=s%3600/60|0,x=s%60;return h?`${h}:${String(m).padStart(2,0)}:${String(x).padStart(2,0)}`:`${m}:${String(x).padStart(2,0)}`};
async function tick(){
 try{const s=await (await fetch('/status',{cache:'no-store'})).json();
  if(!s.total){$('sub').textContent='No run yet. Start photos_to_prompts.py.';return}
  $('sub').textContent=(s.finished?'Finished':'Running')+' · updated '+s.updated+' · folder '+(s.source_dir||'');
  $('fill').style.width=s.percent+'%';
  $('stats').innerHTML=`<span><b>${s.done}</b> of <b>${s.total}</b> (${s.percent}%)</span><span>elapsed <b>${f(s.elapsed_s)}</b></span><span>ETA <b>${s.finished?'–':f(s.eta_s)}</b></span><span class="ok">ok ${s.ok}</span><span>skipped ${s.skipped}</span><span class="${s.failed?'bad':''}">failed ${s.failed}</span>`;
  $('model').textContent=s.model||'–';
  const cur=s.current_file||'';$('file').textContent=cur?`Photo ${s.current_n||Math.min(s.done+1,s.total)} of ${s.total}  ·  ${cur}`:(s.finished?'All done':'');
  if(cur&&cur!==shown){shown=cur;$('img').src='/image?'+Date.now()}
  $('last').textContent=s.last_prompt||'–';
  $('recent').innerHTML=(s.recent||[]).slice().reverse().map(r=>`<li><span>Photo ${r.n}</span><span class="pill ${r.result=='ok'?'ok':r.result=='skipped'?'':'bad'}">${esc(r.result)}</span></li>`).join('');
  if(!sysDone){$('sys').textContent=await (await fetch('/system')).text();sysDone=true}
 }catch(e){$('sub').textContent='dashboard cannot read status'}
}
tick();setInterval(tick,1500);
</script></body></html>"""

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, ctype, body):
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)
    def status(self):
        with open(STATUS, encoding="utf-8") as fh: return json.load(fh)
    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/": return self.send(200, "text/html; charset=utf-8", PAGE.encode())
            if path == "/system": return self.send(200, "text/plain; charset=utf-8", load_system().encode())
            if path == "/status":
                try: return self.send(200, "application/json", json.dumps(self.status()).encode())
                except Exception: return self.send(200, "application/json", b"{}")
            if path == "/image":
                s = self.status(); folder = os.path.realpath(s["source_dir"])
                full = os.path.realpath(os.path.join(folder, s["current_file"]))
                if os.path.dirname(full) != folder or not full.lower().endswith(EXTS): return self.send(404, "text/plain", b"no")
                im = load_image(full); im.thumbnail((900, 1100))
                b = io.BytesIO(); im.save(b, "JPEG", quality=85)
                return self.send(200, "image/jpeg", b.getvalue())
        except Exception: pass
        self.send(404, "text/plain", b"not found")

if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://127.0.0.1:{PORT}"
    print("Dashboard at", url, "(Ctrl+C to stop)")
    threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
