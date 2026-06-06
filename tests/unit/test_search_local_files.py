from pathlib import Path

import pytest

from app.mer_persona.schemas.search import FileSearchRequest
from app.mer_persona.services.search.local_files import LocalFileSearchTool
from app.mer_persona.services.search.tools import ToolExecutionError


@pytest.mark.asyncio
async def test_local_file_search_finds_text(tmp_path: Path):
    root = tmp_path
    target = root / "app" / "example.py"
    target.parent.mkdir(parents=True)
    target.write_text("class IntentRoute:\n    NEEDS_FRESH = 'needs_fresh'\n", encoding="utf-8")

    tool = LocalFileSearchTool(root=root)
    results = await tool.search(FileSearchRequest(query="NEEDS_FRESH", path_scope="app"))

    assert len(results) == 1
    assert results[0].type == "file"
    assert results[0].path == "app/example.py"
    assert results[0].metadata["line"] == 2
    assert "NEEDS_FRESH" in results[0].snippet


@pytest.mark.asyncio
async def test_local_file_search_rejects_missing_scope(tmp_path: Path):
    tool = LocalFileSearchTool(root=tmp_path)
    with pytest.raises(ToolExecutionError) as exc:
        await tool.search(FileSearchRequest(query="x", path_scope="missing"))
    assert "path_scope does not exist" in str(exc.value)


@pytest.mark.asyncio
async def test_local_file_search_rejects_symlink_scope_escape(tmp_path: Path):
    root = tmp_path / "root"
    outside = tmp_path / "root-sibling"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("needle\n", encoding="utf-8")
    link = root / "outside-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    tool = LocalFileSearchTool(root=root)
    with pytest.raises(ToolExecutionError) as exc:
        await tool.search(FileSearchRequest(query="needle", path_scope="outside-link"))
    assert "escapes configured search root" in str(exc.value)


@pytest.mark.asyncio
async def test_local_file_search_respects_top_k(tmp_path: Path):
    root = tmp_path
    target = root / "notes.txt"
    target.write_text("\n".join([f"needle {i}" for i in range(10)]), encoding="utf-8")

    tool = LocalFileSearchTool(root=root)
    results = await tool.search(FileSearchRequest(query="needle", top_k=3))

    assert len(results) == 3
