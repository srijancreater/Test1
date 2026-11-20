"""Vercel Python function: serves the Tender Radar web app.

GET  /            dashboard built from data/sample_tenders.csv (scored against today's date)
POST /?name=x.csv dashboard built from the uploaded CSV / JSON / XML file in the request body
GET  /health      liveness check
"""
from __future__ import annotations

import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tender_radar.config import load_config  # noqa: E402
from tender_radar.pipeline import Filters, run  # noqa: E402
from tender_radar.report import render_html  # noqa: E402

SAMPLE = ROOT / "data" / "sample_tenders.csv"
MAX_UPLOAD = 4 * 1024 * 1024
ALLOWED = {".csv", ".json", ".xml", ".rss", ".atom"}

UPLOAD_FORM = """
<style>.upload{background:var(--card);border:1px dashed var(--line);border-radius:10px;padding:14px;
margin-bottom:20px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.upload button,.upload a{padding:8px 14px;border-radius:8px;border:0;background:var(--accent);color:#fff;
font:inherit;cursor:pointer;text-decoration:none}.upload a{background:transparent;color:var(--accent);
border:1px solid var(--line)}.upload small{color:var(--muted);flex-basis:100%}
.note{color:var(--urgent);font-size:13px;margin:-10px 0 16px}</style>
<form class="upload" id="up"><input type="file" id="file" accept=".csv,.json,.xml,.rss,.atom" required>
<button type="submit">Scan my tenders</button><a href="/">Show demo data</a>
<small>Upload a CSV / JSON / RSS export from GeM, CPPP or your aggregator (max 4 MB).
The file is scored in memory and not stored.</small></form>
<script>document.getElementById('up').addEventListener('submit',async ev=>{ev.preventDefault();
const f=document.getElementById('file').files[0];if(!f)return;
const r=await fetch('/?name='+encodeURIComponent(f.name),{method:'POST',body:await f.arrayBuffer()});
const html=await r.text();document.open();document.write(html);document.close();});</script>
"""


def _page(sources: list[str], subtitle: str, note: str = "") -> str:
    config = load_config(ROOT / "config" / "categories.toml")
    tenders = run(sources, config, Filters())
    extra = UPLOAD_FORM + (f'<p class="note">{note}</p>' if note else "")
    return render_html(tenders, config, header_extra=extra, subtitle=subtitle)


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: str, ctype: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if urlparse(self.path).path.rstrip("/") == "/health":
            return self._send(200, '{"ok": true}', "application/json")
        self._send(200, _page([str(SAMPLE)], "demo data, scored on"))

    def do_POST(self) -> None:  # noqa: N802
        name = parse_qs(urlparse(self.path).query).get("name", ["upload.csv"])[0]
        suffix = Path(name).suffix.lower()
        length = int(self.headers.get("Content-Length") or 0)
        if suffix not in ALLOWED:
            return self._send(400, _page([str(SAMPLE)], "demo data, scored on",
                                         "Unsupported file type. Use .csv, .json or .xml."))
        if not 0 < length <= MAX_UPLOAD:
            return self._send(413, _page([str(SAMPLE)], "demo data, scored on",
                                         "File is empty or larger than 4 MB."))
        body = self.rfile.read(length)
        fd, tmp = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(body)
            html = _page([tmp], f"{Path(name).name}, scored on")
            self._send(200, html)
        except Exception as exc:  # malformed upload: show the demo with an error note
            self._send(400, _page([str(SAMPLE)], "demo data, scored on",
                                  f"Could not read that file: {type(exc).__name__}: {exc}"))
        finally:
            os.unlink(tmp)
