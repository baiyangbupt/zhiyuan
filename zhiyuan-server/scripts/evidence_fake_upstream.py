#!/usr/bin/env python3
"""验收用的上游替身（只在本机回环地址上跑）。

真实上游是 https://www.gaotuzhiyuan.com。它<b>不返回任何数据版本字段</b>（2026-09-11 实测，
见 P1b-1 任务书第二节），所以这个替身也不再伪造 `dataVersion` —— 伪造它会让验收
在一条不存在的契约上通过，P1a 就是这么错的。

「数据版本」现在由 Java 对响应内容算摘要得到，因此验收需要的是
「响应内容存在」与「响应内容缺失/变化」三条分支可复现，替身提供：

  POST /hl-wish/ci/ci_feign/volunteer/querySchoolMajorScoreLine
  GET  /hl-wish/ci/h5/batchData/anno/batchListByPolicy
  POST /hl-wish/ci/ci_feign/volunteer/queryProgramByLimitNum

控制面（只有替身有，真实上游没有）：

  POST /__control/data      {"dataNull": true}                 让所有响应的 data 为 null
  POST /__control/data      {"dataNull": false}                恢复
  POST /__control/content   {"scoreLineMinScore": "620"}       改内容（摘要必须随之变）
  GET  /__control/state                                        当前控制位 + 收到的请求计数
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_MIN_SCORE = "612"

STATE = {
    "dataNull": False,
    "scoreLineMinScore": DEFAULT_MIN_SCORE,
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
        "minScore": STATE["scoreLineMinScore"],
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
                self._write_json({
                    "dataNull": STATE["dataNull"],
                    "scoreLineMinScore": STATE["scoreLineMinScore"],
                    "calls": list(STATE["calls"]),
                })
            return
        self._handle(path)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        body = self._read_json()
        if path == "/__control/data":
            with LOCK:
                STATE["dataNull"] = bool(body.get("dataNull"))
                snapshot = {"dataNull": STATE["dataNull"]}
            self._write_json({"ok": True, **snapshot})
            return
        if path == "/__control/content":
            with LOCK:
                requested = body.get("scoreLineMinScore")
                STATE["scoreLineMinScore"] = DEFAULT_MIN_SCORE if requested is None else str(requested)
                snapshot = {"scoreLineMinScore": STATE["scoreLineMinScore"]}
            self._write_json({"ok": True, **snapshot})
            return
        self._handle(path)

    def _handle(self, path: str) -> None:
        with LOCK:
            STATE["calls"].append(path)
            data_null = STATE["dataNull"]
        payload = _payload(path)
        if data_null:
            payload["data"] = None
        self._write_json(payload)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18999
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    sys.stderr.write("fake-upstream listening on 127.0.0.1:%d\n" % port)
    server.serve_forever()


if __name__ == "__main__":
    main()
