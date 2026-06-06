"""Local lexical file search using ripgrep."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.mer_persona.schemas.search import FileSearchRequest, SearchResult, ToolName
from app.mer_persona.services.search.tools import ToolExecutionError


class LocalFileSearchTool:
    name = ToolName.FILES

    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root).resolve()

    async def search(self, request: FileSearchRequest) -> list[SearchResult]:
        scope = (self.root / request.path_scope).resolve()
        if not str(scope).startswith(str(self.root)):
            raise ToolExecutionError("path_scope escapes configured search root")
        if not scope.exists():
            raise ToolExecutionError(f"path_scope does not exist: {request.path_scope}")

        cmd = [
            "rg",
            "--json",
            "--line-number",
            "--no-heading",
            "--color",
            "never",
        ]
        for glob in request.file_globs:
            cmd.extend(["--glob", glob])
        cmd.extend([request.query, str(scope)])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode not in (0, 1):
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise ToolExecutionError(f"rg failed: {detail}")

        results: list[SearchResult] = []
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            if len(results) >= request.top_k:
                break
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "match":
                continue
            data = event.get("data", {})
            path_text = data.get("path", {}).get("text", "")
            line_number = int(data.get("line_number", 0))
            lines = data.get("lines", {}).get("text", "").rstrip("\n")
            rel_path = str(Path(path_text).resolve().relative_to(self.root))
            results.append(
                SearchResult(
                    type="file",
                    source="local",
                    title=Path(rel_path).name,
                    path=rel_path,
                    snippet=lines,
                    score=1.0,
                    metadata={"line": line_number},
                )
            )
        return results
