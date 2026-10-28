"""Read only the packaged planning skills, without exposing a filesystem tool."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "skills/codex-marketplace/plugins/zhiyuan-codex-planner/skills"
PREFIX = "skill://zhiyuan/"


def skill_files(root: Path = ROOT) -> dict[str, Path]:
    root = root.resolve()
    files = {}
    for pattern in ("*/SKILL.md", "*/references/*.md"):
        for path in sorted(root.glob(pattern)):
            resolved = path.resolve()
            if path.is_symlink() or not resolved.is_relative_to(root) or not resolved.is_file():
                continue
            files[PREFIX + path.relative_to(root).as_posix()] = resolved
    return files


def list_skills(root: Path = ROOT) -> list[dict]:
    return [
        {"uri": uri, "name": uri.removeprefix(PREFIX), "mimeType": "text/markdown"}
        for uri in skill_files(root)
    ]


def read_skill(uri: str, root: Path = ROOT) -> dict:
    path = skill_files(root).get(uri)
    if path is None:
        raise ValueError("unknown_skill_resource")
    if path.stat().st_size > 128 * 1024:
        raise ValueError("skill_resource_too_large")
    return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": path.read_text(encoding="utf-8")}]}


def skill_instructions() -> str:
    names = [uri for uri in skill_files() if uri.endswith("/SKILL.md")]
    return (
        "Planning skills are read-only resources on the zhiyuan_domain MCP server. "
        "Read planner-routing/SKILL.md first, then the selected skill and its references "
        "using list_mcp_resources/read_mcp_resource. Shell is unavailable. "
        "Translate catalog/plugin filesystem paths to resource URIs: the skills root "
        "and its catalog alias r1/ both map to skill://zhiyuan/. For example, "
        "r1/profile-discovery/references/planner-questioning-guide.md means "
        "skill://zhiyuan/profile-discovery/references/planner-questioning-guide.md. "
        "Resolve relative reference paths against the directory of the current "
        "SKILL.md resource URI. list_mcp_resources/read_mcp_resource are skill loading, "
        "not business tool calls, and do not consume a skill business-query budget. "
        "Use only the listed packaged resources; never read arbitrary filesystem paths. "
        "Available resource URIs:\n" + "\n".join(names)
    )
