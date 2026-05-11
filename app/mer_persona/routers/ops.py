import json
import re
import struct
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import HTMLResponse, StreamingResponse

from app.mer_persona.core.config import get_settings
from app.mer_persona.services import eval as eval_svc
from app.shared.db.models import BatchJob, MerBlogComment, MerBlogPost, MerNode
from app.shared.db.session import get_async_session
from app.shared.llm.lmstudio import build_embed_model, build_llm

router = APIRouter(tags=["ops"])
KST = timezone(timedelta(hours=9))


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(KST).isoformat()


def _age_seconds(value: datetime | None) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int((datetime.now(timezone.utc) - value.astimezone(timezone.utc)).total_seconds())


async def _count(session: AsyncSession, model: type[Any]) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return int(result.scalar_one())


def _selected_day(value: str | None) -> date:
    if not value:
        return datetime.now(KST).date()
    try:
        return date.fromisoformat(value)
    except ValueError:
        return datetime.now(KST).date()


def _day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=KST)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


async def _count_between(session: AsyncSession, model: type[Any], column: Any, start: datetime, end: datetime) -> int:
    result = await session.execute(
        select(func.count()).select_from(model).where(column >= start, column < end)
    )
    return int(result.scalar_one())


async def _qdrant_status() -> dict[str, Any]:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{settings.QDRANT_URL.rstrip('/')}/healthz")
        return {"ok": resp.is_success, "status_code": resp.status_code}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def _lmstudio_status() -> dict[str, Any]:
    """LM Studio 서버 & 로드된 모델 목록 확인."""
    settings = get_settings()
    base = settings.LMSTUDIO_BASE_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base}/models")
        if not resp.is_success:
            return {"ok": False, "error": f"HTTP {resp.status_code}"}
        models = [m.get("id", "?") for m in resp.json().get("data", [])]
        return {"ok": True, "models": models}
    except httpx.ConnectError:
        return {"ok": False, "error": "연결 실패 — LM Studio가 실행 중이 아님"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _parse_docker_log_stream(raw: bytes) -> list[str]:
    """Docker multiplexed log stream → 텍스트 라인 목록."""
    lines: list[str] = []
    offset = 0
    while offset + 8 <= len(raw):
        # header: 1B type | 3B padding | 4B size
        size = struct.unpack_from(">I", raw, offset + 4)[0]
        offset += 8
        if offset + size > len(raw):
            break
        chunk = raw[offset: offset + size].decode("utf-8", errors="replace")
        lines.extend(chunk.splitlines())
        offset += size
    return lines


_DOCKER_TS_RE = re.compile(r"^(\S+[+-]\d{2}:\d{2}|\S+Z) ")


def _to_kst_log_lines(lines: list[str]) -> list[str]:
    """Docker가 붙인 UTC 타임스탬프 접두사를 KST로 변환한다."""
    out = []
    for line in lines:
        m = _DOCKER_TS_RE.match(line)
        if m:
            try:
                ts_str = m.group(1).replace("Z", "+00:00")
                dt = datetime.fromisoformat(ts_str).astimezone(KST)
                line = dt.strftime("%m-%d %H:%M:%S") + " " + line[m.end():]
            except Exception:
                pass
        out.append(line)
    return out


async def _docker_logs(container: str = "mer-batch", tail: int = 100) -> list[str]:
    """Docker 소켓으로 컨테이너 로그를 읽는다."""
    try:
        transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
        async with httpx.AsyncClient(
            transport=transport, base_url="http://docker", timeout=5.0
        ) as client:
            resp = await client.get(
                f"/containers/{container}/logs",
                params={"stdout": 1, "stderr": 1, "tail": tail, "timestamps": 1},
            )
        if not resp.is_success:
            return [f"[Docker API error {resp.status_code}]"]
        return _parse_docker_log_stream(resp.content)
    except FileNotFoundError:
        return ["[Docker socket not mounted — /var/run/docker.sock 없음]"]
    except Exception as exc:
        return [f"[Docker log error: {exc}]"]


@router.get("/logs")
async def container_logs(
    container: str = Query("mer-batch"),
    tail: int = Query(100, ge=10, le=500),
):
    """mer-batch 컨테이너 로그를 반환한다."""
    lines = await _docker_logs(container=container, tail=tail)
    return {"container": container, "lines": lines, "count": len(lines)}


@router.get("/batch/status")
async def batch_status(
    selected_date: str | None = Query(None, alias="date"),
    session: AsyncSession = Depends(get_async_session),
):
    day = _selected_day(selected_date)
    start_utc, end_utc = _day_bounds_utc(day)
    latest_job = (
        await session.execute(select(BatchJob).order_by(desc(BatchJob.started_at)).limit(1))
    ).scalar_one_or_none()
    recent_jobs = (
        await session.execute(select(BatchJob).order_by(desc(BatchJob.started_at)).limit(10))
    ).scalars().all()
    latest_post = (
        await session.execute(
            select(MerBlogPost).order_by(desc(MerBlogPost.ingested_at), desc(MerBlogPost.id)).limit(1)
        )
    ).scalar_one_or_none()
    latest_comment = (
        await session.execute(
            select(MerBlogComment)
            .order_by(desc(MerBlogComment.written_at), desc(MerBlogComment.id))
            .limit(1)
        )
    ).scalar_one_or_none()
    selected_jobs = (
        await session.execute(
            select(BatchJob)
            .where(BatchJob.started_at >= start_utc, BatchJob.started_at < end_utc)
            .order_by(desc(BatchJob.started_at))
            .limit(50)
        )
    ).scalars().all()
    selected_posts = (
        await session.execute(
            select(MerBlogPost)
            .where(MerBlogPost.ingested_at >= start_utc, MerBlogPost.ingested_at < end_utc)
            .order_by(desc(MerBlogPost.published_at), desc(MerBlogPost.id))
            .limit(50)
        )
    ).scalars().all()
    selected_comments = (
        await session.execute(
            select(MerBlogComment)
            .where(MerBlogComment.written_at >= start_utc, MerBlogComment.written_at < end_utc)
            .order_by(desc(MerBlogComment.written_at), desc(MerBlogComment.id))
            .limit(20)
        )
    ).scalars().all()

    return {
        "now": datetime.now(timezone.utc).isoformat(),
        "selected_date": day.isoformat(),
        "selected_range_utc": {"start": start_utc.isoformat(), "end": end_utc.isoformat()},
        "counts": {
            "posts": await _count(session, MerBlogPost),
            "comments": await _count(session, MerBlogComment),
            "nodes": await _count(session, MerNode),
            "batch_jobs": await _count(session, BatchJob),
        },
        "selected_counts": {
            "jobs": len(selected_jobs),
            "posts_ingested": await _count_between(
                session, MerBlogPost, MerBlogPost.ingested_at, start_utc, end_utc
            ),
            "comments_written": await _count_between(
                session, MerBlogComment, MerBlogComment.written_at, start_utc, end_utc
            ),
        },
        "latest_job": _job_payload(latest_job),
        "recent_jobs": [_job_payload(job) for job in recent_jobs],
        "selected_jobs": [_job_payload(job) for job in selected_jobs],
        "selected_posts": [
            {
                "post_id_src": post.post_id_src,
                "title": post.title,
                "published_at": _iso(post.published_at),
                "ingested_at": _iso(post.ingested_at),
                "url": post.url,
            }
            for post in selected_posts
        ],
        "selected_comments": [
            {
                "post_id": comment.post_id,
                "author": comment.author,
                "written_at": _iso(comment.written_at),
                "body": comment.body[:120],
            }
            for comment in selected_comments
        ],
        "latest_post": None
        if latest_post is None
        else {
            "post_id_src": latest_post.post_id_src,
            "title": latest_post.title,
            "published_at": _iso(latest_post.published_at),
            "ingested_at": _iso(latest_post.ingested_at),
            "age_seconds": _age_seconds(latest_post.ingested_at),
            "url": latest_post.url,
        },
        "latest_comment": None
        if latest_comment is None
        else {
            "post_id": latest_comment.post_id,
            "author": latest_comment.author,
            "written_at": _iso(latest_comment.written_at),
            "age_seconds": _age_seconds(latest_comment.written_at),
        },
        "qdrant": await _qdrant_status(),
    }


def _job_payload(job: BatchJob | None) -> dict[str, Any] | None:
    if job is None:
        return None
    return {
        "id": job.id,
        "job_name": job.job_name,
        "status": job.status,
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
        "age_seconds": _age_seconds(job.finished_at or job.started_at),
        "rows_total": job.rows_total,
        "rows_done": job.rows_done,
        "meta": job.meta,
    }


@router.get("/batch", response_class=HTMLResponse)
async def batch_dashboard(
    selected_date: str | None = Query(None, alias="date"),
    log_tail: int = Query(80, alias="tail", ge=10, le=500),
    session: AsyncSession = Depends(get_async_session),
):
    settings = get_settings()
    status = await batch_status(selected_date=selected_date, session=session)
    log_lines = _to_kst_log_lines(await _docker_logs(container="mer-batch", tail=log_tail))
    latest_job = status["latest_job"] or {}
    latest_post = status["latest_post"] or {}
    latest_comment = status["latest_comment"] or {}
    qdrant = status["qdrant"]

    job_status = latest_job.get("status", "unknown")
    badge_class = "ok" if job_status in {"ok", "success", "skipped"} else "warn"
    if job_status in {"failed", "running"}:
        badge_class = "bad" if job_status == "failed" else "warn"

    rows = "\n".join(
        f"""
        <tr>
          <td>{escape(str(job["id"]))}</td>
          <td>{escape(job["job_name"])}</td>
          <td><span class="badge {escape(job["status"])}">{escape(job["status"])}</span></td>
          <td>{escape(str(job["started_at"]))}</td>
          <td>{escape(str(job["finished_at"] or "-"))}</td>
          <td>{escape(str(job["rows_done"]))}</td>
          <td><code>{escape(str(job["meta"]))}</code></td>
        </tr>
        """
        for job in status["recent_jobs"]
    )
    selected_job_rows = "\n".join(
        f"""
        <tr>
          <td>{escape(str(job["id"]))}</td>
          <td>{escape(job["job_name"])}</td>
          <td><span class="badge {escape(job["status"])}">{escape(job["status"])}</span></td>
          <td>{escape(str(job["started_at"]))}</td>
          <td>{escape(str(job["finished_at"] or "-"))}</td>
          <td>{escape(str(job["rows_done"]))}</td>
          <td><code>{escape(str(job["meta"]))}</code></td>
        </tr>
        """
        for job in status["selected_jobs"]
    )
    post_rows = "\n".join(
        f"""
        <tr>
          <td>{escape(str(post["ingested_at"] or "-"))}</td>
          <td><a href="{escape(post["url"])}" target="_blank" rel="noreferrer">{escape(post["title"] or post["post_id_src"])}</a></td>
          <td>{escape(str(post["published_at"] or "-"))}</td>
        </tr>
        """
        for post in sorted(status["selected_posts"], key=lambda x: x["published_at"] or "", reverse=True)
    )
    comment_rows = "\n".join(
        f"""
        <tr>
          <td>{escape(str(comment["written_at"] or "-"))}</td>
          <td>{escape(str(comment["author"] or "-"))}</td>
          <td>{escape(comment["body"] or "")}</td>
        </tr>
        """
        for comment in status["selected_comments"]
    )
    selected = escape(status["selected_date"])

    html = f"""
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="300">
  <title>MER Batch Status</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f7f8fa; color: #1f2937; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 28px; }}
    h1 {{ font-size: 24px; margin: 0 0 6px; }}
    .sub {{ color: #6b7280; margin-bottom: 22px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
    .ver-badge {{ margin-left: auto; font-family: "SF Mono", "Fira Code", monospace; font-size: 11px; background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 5px; padding: 2px 8px; color: #64748b; white-space: nowrap; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .card {{ background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; }}
    .label {{ color: #6b7280; font-size: 12px; text-transform: uppercase; }}
    .value {{ font-size: 26px; font-weight: 650; margin-top: 6px; }}
    .wide {{ margin-top: 14px; }}
    .toolbar {{ display: flex; align-items: end; gap: 10px; flex-wrap: wrap; margin: 18px 0 0; }}
    input[type="date"] {{ height: 36px; padding: 0 10px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 14px; }}
    button, .link-button {{ height: 36px; padding: 0 12px; border: 1px solid #d1d5db; border-radius: 6px; background: #ffffff; color: #1f2937; font-size: 14px; text-decoration: none; display: inline-flex; align-items: center; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid #e5e7eb; vertical-align: top; }}
    th {{ color: #6b7280; font-weight: 600; }}
    code {{ white-space: pre-wrap; word-break: break-word; }}
    .badge {{ display: inline-block; padding: 3px 8px; border-radius: 999px; font-size: 12px; font-weight: 650; }}
    .ok, .success, .skipped {{ background: #dcfce7; color: #166534; }}
    .running, .warn {{ background: #fef3c7; color: #92400e; }}
    .failed, .bad {{ background: #fee2e2; color: #991b1b; }}
    .kv {{ display: grid; grid-template-columns: 160px 1fr; gap: 8px 12px; font-size: 14px; }}
    .muted {{ color: #6b7280; }}
    .log-box {{ background: #0f1117; color: #d1fae5; font-family: "SF Mono", "Fira Code", monospace; font-size: 12px; padding: 14px; border-radius: 6px; overflow-x: auto; max-height: 480px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }}
    .log-toolbar {{ display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }}
    @media (max-width: 800px) {{ .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} main {{ padding: 18px; }} }}
  </style>
</head>
<body>
<main>
  <h1>MER Batch Status</h1>
  <div class="sub">
    <span>5분마다 자동 새로고침 · JSON: <a href="/ops/batch/status?date={selected}">/ops/batch/status</a> · <a href="/">← Home</a> · <a href="/ops/eval">RAG 평가</a></span>
    <span class="ver-badge" title="빌드: {escape(settings.BUILD_TIME)}">{escape(settings.GIT_SHA)} · {escape(settings.BUILD_TIME)}</span>
  </div>

  <form class="toolbar" method="get" action="/ops/batch">
    <label>
      <div class="label">조회 날짜</div>
      <input type="date" name="date" value="{selected}">
    </label>
    <button type="submit">조회</button>
    <a class="link-button" href="/ops/batch">오늘</a>
  </form>

  <section class="grid">
    <div class="card"><div class="label">Posts</div><div class="value">{status["counts"]["posts"]:,}</div></div>
    <div class="card"><div class="label">Comments</div><div class="value">{status["counts"]["comments"]:,}</div></div>
    <div class="card"><div class="label">Nodes</div><div class="value">{status["counts"]["nodes"]:,}</div></div>
    <div class="card"><div class="label">Latest Job</div><div class="value"><span class="badge {badge_class}">{escape(job_status)}</span></div></div>
  </section>

  <section class="grid wide">
    <div class="card"><div class="label">Selected Jobs</div><div class="value">{status["selected_counts"]["jobs"]:,}</div></div>
    <div class="card"><div class="label">Posts Ingested</div><div class="value">{status["selected_counts"]["posts_ingested"]:,}</div></div>
    <div class="card"><div class="label">Comments Written</div><div class="value">{status["selected_counts"]["comments_written"]:,}</div></div>
    <div class="card"><div class="label">Selected Date</div><div class="value">{selected}</div></div>
  </section>

  <section class="card wide">
    <h2>Selected Date Batch Runs</h2>
    <table>
      <thead><tr><th>ID</th><th>Job</th><th>Status</th><th>Started</th><th>Finished</th><th>Rows</th><th>Meta</th></tr></thead>
      <tbody>{selected_job_rows or '<tr><td colspan="7" class="muted">No runs for selected date.</td></tr>'}</tbody>
    </table>
  </section>

  <section class="card wide">
    <h2>Posts Ingested On Selected Date</h2>
    <table>
      <thead><tr><th>Ingested</th><th>Title</th><th>Published</th></tr></thead>
      <tbody>{post_rows or '<tr><td colspan="3" class="muted">No posts ingested for selected date.</td></tr>'}</tbody>
    </table>
  </section>

  <section class="card wide">
    <h2>Comments Written On Selected Date</h2>
    <table>
      <thead><tr><th>Written</th><th>Author</th><th>Body</th></tr></thead>
      <tbody>{comment_rows or '<tr><td colspan="3" class="muted">No comments with written_at for selected date.</td></tr>'}</tbody>
    </table>
  </section>

  <section class="card wide">
    <h2>Latest Signals</h2>
    <div class="kv">
      <div class="muted">Last job</div><div>{escape(str(latest_job.get("started_at", "-")))} → {escape(str(latest_job.get("finished_at") or "-"))}</div>
      <div class="muted">Rows</div><div>{escape(str(latest_job.get("rows_done", "-")))} / {escape(str(latest_job.get("rows_total", "-")))}</div>
      <div class="muted">Meta</div><div><code>{escape(str(latest_job.get("meta", "-")))}</code></div>
      <div class="muted">Latest post</div><div>{escape(str(latest_post.get("title", "-")))}</div>
      <div class="muted">Latest comment</div><div>{escape(str(latest_comment.get("author", "-")))} · {escape(str(latest_comment.get("written_at", "-")))}</div>
      <div class="muted">Qdrant</div><div><span class="badge {'ok' if qdrant.get('ok') else 'bad'}">{escape('ok' if qdrant.get('ok') else 'bad')}</span> <code>{escape(str(qdrant))}</code></div>
    </div>
  </section>

  <section class="card wide">
    <h2>Recent Batch Runs</h2>
    <table>
      <thead><tr><th>ID</th><th>Job</th><th>Status</th><th>Started</th><th>Finished</th><th>Rows</th><th>Meta</th></tr></thead>
      <tbody>{rows or '<tr><td colspan="7" class="muted">No batch runs recorded yet.</td></tr>'}</tbody>
    </table>
  </section>

  <section class="card wide">
    <h2>mer-batch 컨테이너 로그</h2>
    <div class="log-toolbar">
      <form method="get" action="/ops/batch" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <input type="hidden" name="date" value="{selected}">
        <label style="font-size:13px;color:#6b7280">최근</label>
        <select name="tail" onchange="this.form.submit()" style="height:32px;padding:0 8px;border:1px solid #d1d5db;border-radius:6px;font-size:13px">
          {''.join(f'<option value="{n}" {"selected" if n == log_tail else ""}>{n}줄</option>' for n in [50, 80, 100, 200, 500])}
        </select>
        <a class="link-button" href="/ops/logs?container=mer-batch&tail={log_tail}" target="_blank" style="font-size:12px">JSON 원문</a>
      </form>
    </div>
    <div class="log-box" id="log-box">{escape(chr(10).join(log_lines)) or '(로그 없음)'}</div>
  </section>
</main>
<script>
  // 로그 박스 자동 스크롤 최하단
  const lb = document.getElementById('log-box');
  if (lb) lb.scrollTop = lb.scrollHeight;
</script>
</body>
</html>
"""
    return HTMLResponse(html)


# ── RAG 평가 대시보드 ──────────────────────────────────────────────────────

@router.get("/eval", response_class=HTMLResponse, include_in_schema=False)
async def eval_dashboard():
    """RAG 품질 평가 대시보드 (SSE 실시간 스트리밍)."""
    settings = get_settings()
    lm_status = await _lmstudio_status()
    return HTMLResponse(_eval_html(settings, lm_status))


@router.get("/eval/stream")
async def eval_stream(
    n: int = Query(default=10, ge=1, le=50),
    judge: bool = Query(default=False),
    session: AsyncSession = Depends(get_async_session),
):
    """SSE 스트림: 샘플 하나씩 평가 결과를 실시간 전송."""
    settings = get_settings()

    def _status(phase: str, msg: str) -> str:
        return f"data: {json.dumps({'type': 'status', 'phase': phase, 'msg': msg}, ensure_ascii=False)}\n\n"

    async def _generate():
        try:
            # ── 즉시 첫 이벤트 전송 (HTTP 버퍼 플러시) ──────────────────────
            yield _status("sampling", "DB에서 샘플 추출 중…")

            author = settings.STYLE_AUTHOR
            samples = await eval_svc.sample_comments(
                session, author, n,
                min_len=settings.STYLE_MIN_LEN,
                max_len=settings.STYLE_MAX_LEN,
                gold_min_len=settings.STYLE_GOLD_MIN_LEN,
            )
            if not samples:
                payload = json.dumps({"type": "error", "msg": "조건에 맞는 샘플이 없습니다."}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
                return

            yield _status("model_init", f"{len(samples)}개 샘플 확보 · 임베딩 모델 준비 중…")
            embed_model = build_embed_model(settings)

            if judge:
                yield _status("model_init", f"{len(samples)}개 샘플 확보 · Judge LLM 준비 중…")
            judge_llm = build_llm(settings, task="verifier") if judge else None

            yield _status("ready", f"{len(samples)}개 샘플 준비 완료 · 평가 시작…")
            api_url = f"http://localhost:{settings.APP_PORT}"

            async for event in eval_svc.stream_eval_batch(samples, embed_model, api_url, judge_llm):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        except Exception as exc:
            payload = json.dumps({"type": "error", "msg": str(exc)}, ensure_ascii=False)
            yield f"data: {payload}\n\n"
        finally:
            yield 'data: {"type":"done"}\n\n'

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _eval_html(settings, lm_status: dict[str, Any] | None = None) -> str:  # type: ignore[no-untyped-def]
    author = escape(settings.STYLE_AUTHOR or "전체")
    min_len = settings.STYLE_MIN_LEN
    max_len = settings.STYLE_MAX_LEN
    gold_min_len = settings.STYLE_GOLD_MIN_LEN
    lm_status = lm_status or {}
    if lm_status.get("ok"):
        models = lm_status.get("models", [])
        lm_banner = (
            f'<div style="background:#f0fdf4;border:1px solid #86efac;border-radius:7px;'
            f'padding:8px 12px;font-size:12px;color:#166534;margin-top:10px;'
            f'word-break:break-word;overflow-wrap:anywhere">'
            f'✅ LM Studio 연결됨 — 로드된 모델: {escape(", ".join(models) or "(없음)")}</div>'
        )
    else:
        err = escape(lm_status.get("error", "알 수 없는 오류"))
        lm_banner = (
            f'<div style="background:#fef2f2;border:1px solid #fca5a5;border-radius:7px;'
            f'padding:8px 12px;font-size:12px;color:#991b1b;margin-top:10px;'
            f'word-break:break-word;overflow-wrap:anywhere">'
            f'❌ LM Studio 연결 실패 — {err}<br>'
            f'<strong>평가를 실행하면 모두 timeout error가 납니다.</strong></div>'
        )
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<title>RAG 평가 | Ops</title>
<style>
  *{{box-sizing:border-box;min-width:0}}
  html,body{{overflow-x:hidden;width:100%}}
  body{{font-family:system-ui,sans-serif;margin:0;background:#f1f5f9;color:#111827}}
  .top{{background:#1f2937;color:#f9fafb;padding:14px 24px;display:flex;align-items:center;gap:16px}}
  .top strong{{font-size:15px}}
  .top a{{color:#9ca3af;text-decoration:none;font-size:13px}}
  .top a:hover{{color:#f9fafb}}
  .top .ver-badge{{margin-left:auto;font-family:"SF Mono","Fira Code",monospace;font-size:11px;
    background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.15);
    border-radius:5px;padding:2px 8px;color:#9ca3af;white-space:nowrap}}
  main{{max-width:1400px;margin:24px auto;padding:0 16px;display:grid;gap:16px}}

  .card{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:20px;overflow:hidden;word-break:break-word;overflow-wrap:anywhere}}
  h2{{margin:0 0 14px;font-size:15px;font-weight:700;color:#1e293b}}

  /* 설정 폼 */
  .settings-row{{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap}}
  .field{{display:flex;flex-direction:column;gap:4px;font-size:13px;color:#6b7280}}
  .field input[type=number]{{width:90px;padding:7px 10px;border:1px solid #d1d5db;border-radius:7px;font-size:14px}}
  .check-label{{flex-direction:row!important;align-items:center;gap:6px;cursor:pointer}}
  .btn{{padding:8px 22px;background:#2563eb;color:#fff;border:0;border-radius:7px;
        cursor:pointer;font-weight:600;font-size:14px;height:36px}}
  .btn:hover{{background:#1d4ed8}}
  .btn:disabled{{background:#93c5fd;cursor:not-allowed}}
  .hint{{font-size:12px;color:#94a3b8;margin-top:8px}}

  /* 진행 상태 */
  #progress-section{{display:none}}
  .progress-bar-wrap{{background:#e2e8f0;border-radius:999px;height:8px;margin-bottom:12px;overflow:hidden}}
  .progress-bar{{height:8px;background:#2563eb;border-radius:999px;transition:width .4s}}
  .progress-bar.pulsing{{
    background:linear-gradient(90deg,#2563eb 0%,#60a5fa 50%,#2563eb 100%);
    background-size:200% 100%;
    animation:pulse-bar 1.4s ease-in-out infinite;
  }}
  @keyframes pulse-bar{{
    0%{{background-position:100% 0}}
    100%{{background-position:-100% 0}}
  }}
  .live-stats{{display:flex;gap:20px;font-size:13px;color:#475569;margin-bottom:10px;flex-wrap:wrap}}
  .live-stat strong{{color:#1e293b}}

  /* 현재 처리 중 샘플 표시 */
  #current-sample{{display:none;align-items:flex-start;gap:10px;
    background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;
    padding:10px 14px;font-size:13px;color:#1e40af;margin-top:4px;
    overflow:hidden;width:100%}}
  .spinner{{width:16px;height:16px;border:2px solid #bfdbfe;
    border-top-color:#2563eb;border-radius:50%;
    animation:spin .7s linear infinite;flex-shrink:0}}
  @keyframes spin{{to{{transform:rotate(360deg)}}}}
  .cur-sample-text{{flex:1;min-width:0;overflow:hidden}}
  .cur-sample-label{{font-weight:700;margin-bottom:1px}}
  .cur-sample-q{{color:#3b82f6;overflow:hidden;word-break:break-word;overflow-wrap:anywhere;
    display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}}
  .cur-sample-timer{{font-variant-numeric:tabular-nums;color:#6b7280;flex-shrink:0;font-size:12px}}

  /* 결과 테이블 — 카드 overflow:hidden 이 스크롤 막지 않도록 */
  #result-section{{overflow:visible}}
  .table-wrap{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
  table{{width:100%;min-width:700px;border-collapse:collapse;font-size:13px;table-layout:fixed}}
  th{{background:#f8fafc;padding:9px 10px;text-align:left;font-weight:600;
      font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:#64748b;
      border-bottom:2px solid #e2e8f0;white-space:nowrap}}
  td{{padding:0;border-bottom:1px solid #f1f5f9;vertical-align:top;word-break:break-word}}
  tr.result-row:hover td{{background:#f8fafc}}

  /* 행 내부 */
  .cell{{padding:10px 10px}}
  .q-text{{font-weight:600;color:#1e293b;margin-bottom:2px}}
  .q-sub{{font-size:11px;color:#94a3b8}}

  .score{{font-size:15px;font-weight:700;text-align:center}}
  .score.hi{{color:#16a34a}}
  .score.mid{{color:#d97706}}
  .score.lo{{color:#dc2626}}
  .score.err{{color:#94a3b8}}

  /* 답변 비교 토글 */
  .toggle-btn{{font-size:11px;color:#3b82f6;cursor:pointer;border:none;
               background:none;padding:0;text-decoration:underline}}
  .compare-block{{display:none;margin-top:8px}}
  .compare-block.open{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px;min-width:0}}
  .compare-col{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:7px;padding:10px;
               font-size:12px;line-height:1.6;min-width:0;overflow:hidden}}
  .compare-col h4{{margin:0 0 6px;font-size:11px;text-transform:uppercase;
                   letter-spacing:.06em;color:#64748b;font-weight:700}}
  .compare-col p{{margin:0;white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere}}
  .gold-col h4{{color:#0369a1}}
  .gen-col h4{{color:#7c3aed}}

  /* badge */
  .badge{{display:inline-block;padding:2px 7px;border-radius:5px;font-size:11px;font-weight:600}}
  .badge-blue{{background:#dbeafe;color:#1d4ed8}}
  .badge-gray{{background:#f1f5f9;color:#64748b}}
  .badge-red{{background:#fee2e2;color:#991b1b}}

  /* 요약 */
  #summary-section{{display:none}}
  .summary-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px}}
  .s-card{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:9px;padding:14px}}
  .s-label{{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#94a3b8;font-weight:700}}
  .s-value{{font-size:22px;font-weight:700;margin-top:4px;color:#1e293b}}
  .dist-wrap{{display:flex;flex-direction:column;gap:5px}}
  .dist-row{{display:flex;align-items:center;gap:8px;font-size:12px}}
  .dist-label{{width:68px;color:#6b7280;flex-shrink:0}}
  .dist-bar{{height:14px;background:#3b82f6;border-radius:3px;min-width:3px;transition:width .5s}}
  .dist-cnt{{color:#374151;font-weight:600}}
</style>
</head>
<body>
<div class="top">
  <strong>RAG 품질 평가</strong>
  <a href="/">← Home</a>
  <a href="/ops/batch">Batch</a>
  <a href="/mer/chat">Chat →</a>
  <span class="ver-badge" title="빌드: {escape(settings.BUILD_TIME)}">{escape(settings.GIT_SHA)} · {escape(settings.BUILD_TIME)}</span>
</div>
<main>

  <!-- 설정 -->
  <section class="card">
    <h2>평가 설정</h2>
    <div class="settings-row">
      <label class="field">샘플 수
        <input type="number" id="nInput" value="10" min="1" max="50"/>
      </label>
      <label class="field check-label">
        <input type="checkbox" id="judgeInput"/>
        LLM judge (느림)
      </label>
      <button class="btn" id="startBtn" onclick="startEval()">▶ 평가 실행</button>
      <button class="btn" id="stopBtn" onclick="stopEval()"
              style="background:#6b7280;display:none">■ 중단</button>
    </div>
    <div class="hint">
      author={author} · len={min_len}~{max_len}자 ·
      질문 소스: <strong>타인 댓글 → 메르 대댓글</strong> (parent_id 없으면 포스트 제목 fallback) · gold ≥ {gold_min_len}자 ·
      대용량: <code>python scripts/eval_rag.py --n 100 --judge</code>
    </div>
    {lm_banner}
  </section>

  <!-- 진행 표시 -->
  <section class="card" id="progress-section">
    <h2>진행 중 <span id="prog-text" style="font-weight:400;color:#64748b"></span></h2>
    <div class="progress-bar-wrap"><div class="progress-bar pulsing" id="prog-bar" style="width:0%"></div></div>
    <div class="live-stats">
      <span>완료: <strong id="stat-ok">0</strong> / <strong id="stat-total">?</strong></span>
      <span>코사인 평균: <strong id="stat-avg">-</strong></span>
      <span>총 경과: <strong id="stat-elapsed">0s</strong></span>
    </div>
    <!-- 현재 처리 중인 샘플 -->
    <div id="current-sample">
      <div class="spinner"></div>
      <div class="cur-sample-text">
        <div class="cur-sample-label" id="cur-label">샘플 처리 중...</div>
        <div class="cur-sample-q" id="cur-question"></div>
      </div>
      <div class="cur-sample-timer" id="cur-timer">0s</div>
    </div>
  </section>

  <!-- 상세 결과 테이블 -->
  <section class="card" id="result-section" style="display:none">
    <h2>상세 결과</h2>
    <div class="table-wrap">
      <table>
        <colgroup>
          <col style="width:36px"/>
          <col/>
          <col style="width:110px"/>
          <col style="width:80px"/>
          <col style="width:64px"/>
          <col style="width:64px"/>
          <col style="width:48px"/>
        </colgroup>
        <thead>
          <tr>
            <th>#</th>
            <th>질문</th>
            <th>intent</th>
            <th style="text-align:center">코사인</th>
            <th style="text-align:center">judge</th>
            <th style="text-align:center">지연</th>
            <th></th>
          </tr>
        </thead>
        <tbody id="result-tbody"></tbody>
      </table>
    </div>
  </section>

  <!-- 최종 요약 -->
  <section class="card" id="summary-section">
    <h2>최종 요약</h2>
    <div class="summary-grid" id="summary-grid"></div>
    <div class="dist-wrap" id="dist-wrap"></div>
  </section>

</main>

<script>
let es = null;
let startTime = 0;
let elapsedTimer = null;
let nTotal = 0;
let curSampleStart = 0;
let curSampleTimer = null;

function startEval() {{
  const n = parseInt(document.getElementById('nInput').value) || 10;
  const judge = document.getElementById('judgeInput').checked;

  // 리셋
  document.getElementById('result-tbody').innerHTML = '';
  document.getElementById('summary-grid').innerHTML = '';
  document.getElementById('dist-wrap').innerHTML = '';
  document.getElementById('progress-section').style.display = 'block';
  document.getElementById('result-section').style.display = 'none';
  document.getElementById('summary-section').style.display = 'none';
  document.getElementById('prog-bar').style.width = '100%'; // 시작부터 바가 보이도록
  document.getElementById('stat-ok').textContent = '0';
  document.getElementById('stat-avg').textContent = '-';
  document.getElementById('stat-total').textContent = '?';
  document.getElementById('prog-text').textContent = '';
  document.getElementById('startBtn').disabled = true;
  document.getElementById('stopBtn').style.display = '';

  // ── 버튼 클릭 즉시 "초기화 중" 스피너 표시 ──
  const curEl = document.getElementById('current-sample');
  curEl.style.display = 'flex';
  document.getElementById('cur-label').textContent = '서버 연결 중…';
  document.getElementById('cur-question').textContent = 'SSE 스트림 오픈 대기';
  document.getElementById('cur-timer').textContent = '';

  startTime = Date.now();
  elapsedTimer = setInterval(() => {{
    document.getElementById('stat-elapsed').textContent =
      ((Date.now() - startTime) / 1000).toFixed(0) + 's';
  }}, 1000);

  const url = `/ops/eval/stream?n=${{n}}&judge=${{judge}}`;
  es = new EventSource(url);

  es.onmessage = (e) => {{
    const ev = JSON.parse(e.data);
    if (ev.type === 'status') {{
      // 초기화 단계 상태 메시지
      const phaseIcon = {{
        sampling:   '🗄️',
        model_init: '⚙️',
        ready:      '✅',
      }}[ev.phase] || '⏳';
      document.getElementById('cur-label').textContent = phaseIcon + ' ' + ev.msg;
      document.getElementById('cur-question').textContent = '';
      document.getElementById('cur-timer').textContent = '';

    }} else if (ev.type === 'start') {{
      nTotal = ev.n_total;
      document.getElementById('stat-total').textContent = nTotal;
      document.getElementById('result-section').style.display = 'block';
      document.getElementById('cur-label').textContent = `✅ ${{nTotal}}개 샘플 준비 완료 — 첫 번째 샘플 시작 중…`;
      document.getElementById('cur-question').textContent = '';
      // 진행 바를 0%로 리셋 (실제 진행률로 관리)
      document.getElementById('prog-bar').style.width = '0%';

    }} else if (ev.type === 'processing') {{
      // 샘플 처리 시작 — 현재 처리 중 표시
      clearInterval(curSampleTimer);
      curSampleStart = Date.now();
      const curEl = document.getElementById('current-sample');
      curEl.style.display = 'flex';
      document.getElementById('cur-label').textContent =
        `샘플 ${{ev.idx}} / ${{nTotal}} 처리 중 (LLM 호출 대기)`;
      document.getElementById('cur-question').textContent = ev.question;
      document.getElementById('cur-timer').textContent = '0s';
      curSampleTimer = setInterval(() => {{
        const sec = ((Date.now() - curSampleStart) / 1000).toFixed(0);
        document.getElementById('cur-timer').textContent = sec + 's';
      }}, 500);

    }} else if (ev.type === 'sample') {{
      // 샘플 완료 — 현재 처리 중 표시 숨기고 행 추가
      clearInterval(curSampleTimer);
      document.getElementById('current-sample').style.display = 'none';
      appendRow(ev);
      // 진행률
      const pct = Math.round((ev.idx / nTotal) * 100);
      document.getElementById('prog-bar').style.width = pct + '%';
      document.getElementById('prog-text').textContent =
        ev.idx + ' / ' + nTotal + ' (' + pct + '%)';
      document.getElementById('stat-ok').textContent = ev.running_ok ?? '-';
      if (ev.running_avg != null)
        document.getElementById('stat-avg').textContent = ev.running_avg.toFixed(3);

    }} else if (ev.type === 'summary') {{
      showSummary(ev);
    }} else if (ev.type === 'error') {{
      clearInterval(curSampleTimer);
      document.getElementById('current-sample').style.display = 'none';
      alert('오류: ' + ev.msg);
      cleanup();
    }} else if (ev.type === 'done') {{
      clearInterval(curSampleTimer);
      document.getElementById('current-sample').style.display = 'none';
      // 완료 후 progress bar 펄싱 제거
      document.getElementById('prog-bar').classList.remove('pulsing');
      cleanup();
    }}
  }};

  es.onerror = () => {{
    cleanup();
  }};
}}

function stopEval() {{
  if (es) es.close();
  cleanup();
}}

function cleanup() {{
  if (es) {{ es.close(); es = null; }}
  clearInterval(elapsedTimer);
  clearInterval(curSampleTimer);
  document.getElementById('startBtn').disabled = false;
  document.getElementById('stopBtn').style.display = 'none';
  document.getElementById('prog-bar').classList.remove('pulsing');
  document.getElementById('current-sample').style.display = 'none';
}}

function cosineColor(v) {{
  if (v == null) return 'err';
  if (v >= 0.7) return 'hi';
  if (v >= 0.5) return 'mid';
  return 'lo';
}}

let rowId = 0;
function appendRow(ev) {{
  const id = 'row-' + (++rowId);
  const cosineStr = ev.cosine != null ? ev.cosine.toFixed(3) : '-';
  const judgeStr  = ev.judge_score != null ? ev.judge_score.toFixed(1) : '-';
  const cls = cosineColor(ev.cosine);

  // 에러 메시지 파싱: "error:ReadTimeout..." 에서 원인만 추출
  const errMsg = ev.error ? ev.error.replace(/^error:/, '') : '';
  const intentBadge = ev.error
    ? `<span class="badge badge-red" title="${{esc(errMsg)}}">error</span>`
    : `<span class="badge badge-blue">${{esc(ev.intent)}}</span>`;

  const tr = document.createElement('tr');
  tr.className = 'result-row';
  tr.innerHTML = `
    <td><div class="cell" style="color:#94a3b8;font-size:12px">${{ev.idx}}</div></td>
    <td>
      <div class="cell">
        <div class="q-text">${{esc(ev.question)}}</div>
        ${{ev.error
          ? `<div class="q-sub" style="color:#dc2626">⚠ ${{esc(errMsg.slice(0,80))}}</div>`
          : `<div class="q-sub">gold: ${{esc(ev.gold.slice(0,60))}}${{ev.gold.length > 60 ? '…' : ''}}</div>`
        }}
      </div>
    </td>
    <td><div class="cell">${{intentBadge}}</div></td>
    <td><div class="cell score ${{cls}}">${{cosineStr}}</div></td>
    <td><div class="cell" style="text-align:center;color:#6b7280">${{judgeStr}}</div></td>
    <td><div class="cell" style="text-align:center;color:#94a3b8">${{ev.latency_s}}s</div></td>
    <td><div class="cell">
      ${{ev.error ? '' : `<button class="toggle-btn" onclick="toggleCompare('${{id}}')">비교 ▾</button>`}}
    </div></td>
  `;

  // 비교 행 (에러 시 에러 메시지 전체 표시, 정상 시 gold vs generated)
  const compareRow = document.createElement('tr');
  compareRow.id = id;
  compareRow.style.display = 'none';
  const compareInner = ev.error
    ? `<td colspan="7" style="padding:0 10px 12px">
        <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:7px;
                    padding:12px;font-size:12px;color:#991b1b;white-space:pre-wrap">
          <strong>에러 상세:</strong>\n${{esc(errMsg)}}
        </div>
       </td>`
    : `<td colspan="7" style="padding:0 10px 12px">
        <div class="compare-block open">
          <div class="compare-col gold-col">
            <h4>📌 Gold (메르 실제 대댓글)</h4>
            <p>${{esc(ev.gold)}}</p>
          </div>
          <div class="compare-col gen-col">
            <h4>🤖 Generated (RAG 답변)</h4>
            <p>${{esc(ev.generated || '(생성 실패)')}}</p>
          </div>
        </div>
       </td>`;
  compareRow.innerHTML = compareInner;

  const tbody = document.getElementById('result-tbody');
  tbody.appendChild(tr);
  tbody.appendChild(compareRow);
  tbody.scrollIntoView({{behavior:'smooth', block:'end'}});
}}

function toggleCompare(id) {{
  const row = document.getElementById(id);
  row.style.display = row.style.display === 'none' ? '' : 'none';
}}

function showSummary(ev) {{
  document.getElementById('summary-section').style.display = 'block';

  const grid = document.getElementById('summary-grid');
  const avg = ev.avg_cosine != null ? ev.avg_cosine.toFixed(3) : '-';
  const mn  = ev.min_cosine != null ? ev.min_cosine.toFixed(3) : '-';
  const mx  = ev.max_cosine != null ? ev.max_cosine.toFixed(3) : '-';
  const judge = ev.avg_judge != null ? ev.avg_judge.toFixed(2) + '/5' : '-';

  grid.innerHTML = `
    <div class="s-card">
      <div class="s-label">성공 / 전체</div>
      <div class="s-value">${{ev.n_ok}} <span style="font-size:15px;color:#94a3b8">/ ${{ev.n_total}}</span></div>
    </div>
    <div class="s-card">
      <div class="s-label">코사인 평균</div>
      <div class="s-value">${{avg}}</div>
      <div style="font-size:12px;color:#94a3b8;margin-top:2px">min ${{mn}} · max ${{mx}}</div>
    </div>
    <div class="s-card">
      <div class="s-label">LLM judge avg</div>
      <div class="s-value">${{judge}}</div>
    </div>`;

  const distWrap = document.getElementById('dist-wrap');
  const maxCnt = Math.max(...(ev.buckets || []).map(b => b[1]), 1);
  distWrap.innerHTML = (ev.buckets || []).map(([lbl, cnt]) => `
    <div class="dist-row">
      <span class="dist-label">${{lbl}}</span>
      <span class="dist-bar" style="width:${{Math.round(cnt/maxCnt*160)}}px"></span>
      <span class="dist-cnt">${{cnt}}</span>
    </div>`).join('');
}}

function esc(s) {{
  return String(s ?? '')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}
</script>
</body>
</html>"""
