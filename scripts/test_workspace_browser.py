"""Optional real-browser regressions. Uses synthetic data; no live tracker is contacted."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
CHROME = os.environ.get("TRACKER_TEST_CHROME") or shutil.which("chromium") or shutil.which("google-chrome")
if not CHROME:
    candidate = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    CHROME = str(candidate) if candidate.exists() else None

BROWSER_CHECK = r"""
window.addEventListener("error", event => { window.testError = event.message; });
let testStale = false, testOffline = false;
window.fetch = async () => {
  if (testOffline) throw new Error("Synthetic offline");
  return {ok:true, json:async () => ({
    updated_at:Date.now()/1000, interval:3600, stale:testStale,
    agents:[
      {id:"root",provider:"codex",project:"Example",path:"/example",state:"working",role:"builder",task:"Synthetic assignment",source:"Synthetic source",updated_at:Date.now()/1000},
      {id:"child",parent_id:"root",provider:"claude",project:"Example",path:"/example",state:"waiting",role:"reviewer",task:"Synthetic review",source:"Synthetic source",updated_at:Date.now()/1000},
      {id:"past",provider:"codex",project:"Example",path:"/example",state:"recent",task:"Historical task",source:"Synthetic history",updated_at:1}
    ],
    projects:[{name:"Example",path:"/example",branch:"main"}],
    sources:[{name:"Synthetic source",ok:true}],roles:[],policy:{}
  })};
};
window.addEventListener("load", async () => {
  const output = document.createElement("pre");
  output.id = "browser-test-result";
  document.body.append(output);
  const check = (condition,message) => {if (!condition) throw new Error(message);};
  const until = async predicate => {
    for (let i=0;i<100;i++) {if (predicate()) return; await new Promise(resolve=>setTimeout(resolve,20));}
    throw new Error("Readiness timeout");
  };
  try {
    await until(()=>document.querySelectorAll(".world-agent").length===2);
    check(!window.testError, window.testError);
    check(document.getElementById("recent").textContent.includes("Historical task"),"History missing");
    const viewport=document.getElementById("world-viewport");
    viewport.focus();
    const initialCamera=document.getElementById("world").getAttribute("style");
    viewport.dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowLeft",bubbles:true}));
    check(document.getElementById("world").getAttribute("style")!==initialCamera,"Keyboard orbit failed");
    document.getElementById("reset-camera").click();
    const first=document.querySelector(".world-agent");
    first.scrollIntoView({block:"center",behavior:"instant"});
    const face=first.querySelector(".robot-head .solid-front");
    const rect=face.getBoundingClientRect();
    const hit=document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2);
    check(hit && hit.closest(".world-agent")===first,"Robot model is not pointer selectable: "+JSON.stringify({rect:rect.toJSON(),hit:hit && hit.className,width:innerWidth,height:innerHeight}));
    hit.click();
    check(document.getElementById("agent-inspector").textContent.includes("Synthetic assignment"),"Selection details missing");
    const world=document.getElementById("world"), before=world.getAttribute("style");
    document.getElementById("zoom-in").click();
    check(world.getAttribute("style")!==before,"Zoom did not change camera");
    document.getElementById("reset-camera").click();
    document.getElementById("view-list").click();
    check(!document.getElementById("list-view").hidden && document.getElementById("workspace").hidden,"List toggle failed");
    document.getElementById("view-world").click();
    const search=document.getElementById("search");
    search.value="no matching synthetic session"; search.dispatchEvent(new Event("input"));
    check(document.querySelectorAll(".world-agent").length===0,"Search did not filter scene");
    check(!document.getElementById("world-empty").hidden,"Empty state missing");
    search.value=""; search.dispatchEvent(new Event("input"));
    check(document.querySelectorAll(".world-agent").length===2,"Search recovery failed");
    const focused=document.querySelector(".world-agent");
    focused.click(); focused.focus();
    testStale=true; document.getElementById("refresh").click();
    await until(()=>document.getElementById("connection").textContent.includes("out of date"));
    check(document.activeElement.classList.contains("world-agent"),"Polling lost agent focus");
    check(document.getElementById("agent-inspector").textContent.includes("Unknown"),"Inspector did not refresh stale selection");
    check(!document.querySelector(".world-agent.working, .world-agent.waiting"),"Stale scene presents live status");
    check(document.getElementById("working-count").textContent==="0","Stale working count");
    testOffline=true; document.getElementById("refresh").click();
    await until(()=>!document.getElementById("refresh").disabled);
    check(!document.getElementById("source-alert").hidden,"Offline warning missing");
    check(!window.testError,window.testError);
    check(document.documentElement.scrollWidth<=window.innerWidth,"Page overflows viewport");
    output.textContent="BROWSER PASS";
  } catch(error) {output.textContent="BROWSER FAIL: "+error.message;}
});
"""

@unittest.skipUnless(CHROME, "Chrome/Chromium unavailable; set TRACKER_TEST_CHROME")
class WorkspaceBrowserTests(unittest.TestCase):
    def test_workspace_desktop_and_narrow(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/":
                    page = (ROOT / "dashboard/index.html").read_text()
                    page = page.replace('<script src="/app.js"', "<script>" + BROWSER_CHECK + '</script><script src="/app.js"')
                    body, mime = page.encode(), "text/html"
                elif self.path in ("/app.js", "/style.css"):
                    body = (ROOT / "dashboard" / self.path[1:]).read_bytes()
                    mime = "text/javascript" if self.path.endswith(".js") else "text/css"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for size in ("1440,1000", "500,844"):
                with self.subTest(viewport=size), tempfile.TemporaryDirectory() as profile:
                    result = subprocess.run([
                        CHROME, "--headless", "--no-first-run", "--no-default-browser-check",
                        "--disable-background-networking", "--disable-gpu",
                        "--user-data-dir=" + profile, "--window-size=" + size,
                        "--virtual-time-budget=5000", "--dump-dom",
                        "http://127.0.0.1:" + str(server.server_port) + "/"
                    ], capture_output=True, text=True, timeout=40)
                    self.assertEqual(result.returncode, 0, result.stderr[-2000:])
                    marker = result.stdout.rsplit('id="browser-test-result"', 1)[-1].split("</pre>", 1)[0]
                    self.assertIn(">BROWSER PASS", marker, marker[:1000])
        finally:
            server.shutdown()
            server.server_close()
