import json
import os
import subprocess
import sys
from pathlib import Path


def _list_tools(tmp_path: Path) -> list[dict]:
    fixture = Path(__file__).parents[1] / "fixtures" / "mcp" / "semantic_readonly_server.py"
    process = subprocess.Popen(
        [sys.executable, str(fixture)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "ZHIYUAN_SEMANTIC_MCP_TRACE": str(tmp_path / "trace.jsonl")},
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}) + "\n")
    process.stdin.flush()
    result = json.loads(process.stdout.readline())
    process.terminate()
    return result["result"]["tools"]


def test_semantic_readonly_server_lists_only_read_tools(tmp_path: Path) -> None:
    names = {tool["name"] for tool in _list_tools(tmp_path)}
    assert names == {"catalog.search_schools", "admission.get_history"}


def test_semantic_readonly_server_marks_every_tool_read_only(tmp_path: Path) -> None:
    for tool in _list_tools(tmp_path):
        assert tool.get("annotations", {}).get("readOnlyHint") is True, tool["name"]
