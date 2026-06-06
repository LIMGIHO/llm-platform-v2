"""Local lexical file search using ripgrep."""
from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from pathlib import Path

from app.mer_persona.schemas.search import FileSearchRequest, SearchResult, ToolName
from app.mer_persona.services.search.tools import ToolExecutionError


class LocalFileSearchTool:
    name = ToolName.FILES

    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root).resolve()

    async def search(self, request: FileSearchRequest) -> list[SearchResult]:
        scope = (self.root / request.path_scope).resolve()
        try:
            scope.relative_to(self.root)
        except ValueError as exc:
            raise ToolExecutionError("path_scope escapes configured search root") from exc
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

        results: list[SearchResult] = []
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise ToolExecutionError(f"rg is not available: {exc}") from exc

        assert proc.stdout is not None
        try:
            while len(results) < request.top_k:
                raw_line = await proc.stdout.readline()
                if not raw_line:
                    break
                try:
                    event = json.loads(raw_line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                if event.get("type") != "match":
                    continue
                data = event.get("data", {})
                path_text = data.get("path", {}).get("text", "")
                line_number = int(data.get("line_number", 0))
                lines = data.get("lines", {}).get("text", "").rstrip("\n")
                rel_path = Path(path_text).resolve().relative_to(self.root).as_posix()
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

            if len(results) >= request.top_k and proc.returncode is None:
                proc.terminate()
            _, stderr = await proc.communicate()
        except OSError as exc:
            raise ToolExecutionError(f"rg failed: {exc}") from exc
        finally:
            if proc.returncode is None:
                with suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()

        if proc.returncode not in (0, 1, -15):
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise ToolExecutionError(f"rg failed: {detail}")
        return results
