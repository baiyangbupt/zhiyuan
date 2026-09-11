#!/usr/bin/env python3
"""P1a 验收用的上游替身（只在本机回环地址上跑）。

真实上游是 https://www.gaotuzhiyuan.com，从验收环境不可达，且它是否返回
dataVersion 不由我们决定。验收需要的是「上游版本存在」和「上游版本缺失」
两条分支都可复现，所以这里用替身提供：

  POST /hl-wish/ci/ci_feign/volunteer/querySchoolMajorScoreLine
  GET  /hl-wish/ci/h5/batchData/anno/batchListByPolicy
  POST /hl-wish/ci/ci_feign/volunteer/queryProgramByLimitNum

控制面（只有替身有，真实上游没有）：

  POST /__control/version  {"dataVersion": "2026-06-v17"}   设版本，null 表示不返回版本字段
  GET  /__control/state                                     当前版本 + 收到的请求计数
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = {
    "dataVersion": "2026-06-v17",
    "calls": [],
}
LOCK = threading.Lock()

SCORE_LINE_PATH = "/hl-wish/ci/ci_feign/volunteer/querySchoolMajorScoreLine"
BATCH_LIST_PATH = "/hl-wish/ci/h5/batchData/anno/batchListByPolicy"
PROGRAM_LIMIT_PATH = "/hl-wish/ci/ci_feign/volunteer/queryProgramByLimitNum"


def _score_line_row() -> dict:
    return {
        "year": 2025,
        "name": "甲大学",
        "batch": "本科批",
        "batchTitle": "本科批",
        "enrollNum": "10",
        "maxScore": "630",
        "minScore": "612",
        "averageScore": "620",
        "minPos": "8000",
        "maxPos": "12000",
        "selectInfo": "物理类",
    }


def _payload(path: str) -> dict:
    if path == SCORE_LINE_PATH:
        return {"code": 0, "msg": "ok", "data": [_score_line_row()]}
    if path == BATCH_LIST_PATH:
        return {
            "code": 0,
            "msg": "ok",
            "data": {
                "year": "2026",
                "baseYear": "2026",
                "converYear": "2025",
                "area": {"id": "330000", "name": "浙江"},
                "batchList": [
                    {
                        "id": "batch-1",
                        "year": "2026",
                        "batch": "本科批",
                        "batchTitle": "本科批",
                        "score": "492",
                        "pos": 170000,
                        "subject": {"code": "physics", "desc": "物理类"},
                        "level": {"id": "bachelor", "name": "本科"},
                    }
                ],
                "type": {"code": "bachelor", "desc": "本科"},
            },
        }
    if path == PROGRAM_LIMIT_PATH:
        return {
            "code": 0,
            "msg": "ok",
            "data": [{"volunteerLevel": "冲", "records": []}],
        }
    return {"code": 404, "msg": "unknown path", "data": None}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 保持验收输出干净
        sys.stderr.write("fake-upstream: " + (fmt % args) + "\n")

    def _write_json(self, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return {}

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/__control/state":
            with LOCK:
                self._write_json({"dataVersion": STATE["dataVersion"], "calls": list(STATE["calls"])})
            return
        self._handle(path)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        body = self._read_json()
        if path == "/__control/version":
            with LOCK:
                STATE["dataVersion"] = body.get("dataVersion")
            self._write_json({"ok": True, "dataVersion": STATE["dataVersion"]})
            return
        self._handle(path)

    def _handle(self, path: str) -> None:
        with LOCK:
            STATE["calls"].append(path)
            version = STATE["dataVersion"]
        payload = _payload(path)
        if version is not None:
            payload["dataVersion"] = version
        self._write_json(payload)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18999
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    sys.stderr.write("fake-upstream listening on 127.0.0.1:%d\n" % port)
    server.serve_forever()


if __name__ == "__main__":
    main()
