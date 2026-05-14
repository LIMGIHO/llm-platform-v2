"""POST /v1/mer/answer — Hybrid RAG 답변 + POST /v1/mer/retrieve — 디버그용."""
from __future__ import annotations

import asyncio
import json
import time
import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from llama_index.llms.openai_like import OpenAILike
from sqlalchemy.ext.asyncio import AsyncSession

from app.mer_persona.core.config import Settings, get_settings
from app.mer_persona.core.deps import db_session, get_llm, get_redis
from app.mer_persona.core.logging import get_logger
from app.mer_persona.core.metrics import (
    ANSWER_LATENCY,
    ANSWER_REQUESTS,
    LLM_CALLS,
    LLM_ERRORS,
    RETRIEVE_NODES,
)
from app.mer_persona.schemas.mer import (
    AnswerRequest,
    Citation,
    MerAnswerResponse,
    RoutingCard,
    VerifierResult,
)
from app.mer_persona.schemas.retrieve import RetrieveRequest, RetrieveResponse, RetrievedNode
from app.mer_persona.services import tracing
from app.mer_persona.services.index import bm25_index, vector_index
from app.mer_persona.services.mer import (
    blog_post_query,
    context_resolver,
    evidence_builder,
    intent_router,
    prompt_builder,
    response_synthesizer,
    style_pack_builder,
    verifier as verifier_svc,
)
from app.mer_persona.services.retrieval import hybrid_retriever, query_rewriter, reranker

router = APIRouter(tags=["mer"])
logger = get_logger(__name__)


async def _load_recent_turns(
    redis: aioredis.Redis,
    conversation_id: str | None,
) -> list[tuple[str, str]]:
    """Redis 히스토리에서 최근 2턴(최대 4 messages)을 로드한다."""
    if not conversation_id:
        return []
    try:
        raw = await redis.get(f"conv:{conversation_id}:messages")
        if not raw:
            return []
        messages: list[dict] = json.loads(raw)
        return [(m["role"], m["content"]) for m in messages[-4:]]
    except Exception:
        return []


async def _retrieve_nodes(query: str, top_k: int, settings: Settings, llm: OpenAILike | None = None):
    queries = await query_rewriter.rewrite(query, llm=llm)
    search_query = queries[0]

    # mer_blog(블로그 포스트) + mer_comments(댓글) 동시 검색
    blog_ret = vector_index.get_vector_retriever(top_k=top_k * 2)
    comments_ret = vector_index.get_comments_vector_retriever(top_k=top_k * 2)
    bm25_ret = bm25_index.get_bm25_retriever(top_k=top_k * 2)
    retriever = hybrid_retriever.get_hybrid_retriever(
        blog_ret, bm25_ret, comments_retriever=comments_ret, top_k=top_k * 2
    )

    nodes = await retriever.aretrieve(search_query)
    nodes = await reranker.rerank(nodes, query=query, top_k=top_k)

    floor = settings.ANSWER_SCORE_FLOOR
    nodes = [n for n in nodes if (n.score or 0.0) >= floor]
    return nodes


@router.post("/answer", response_model=MerAnswerResponse)
async def answer(
    req: AnswerRequest,
    llm: OpenAILike = Depends(get_llm),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(db_session),
    redis: aioredis.Redis = Depends(get_redis),
) -> MerAnswerResponse:
    t0 = time.monotonic()
    trace_id = str(uuid.uuid4())
    # conversation_id가 없으면 신규 생성 — 클라이언트에 반환해서 후속 요청에 재사용
    conversation_id: str = req.conversation_id or str(uuid.uuid4())
    tc = tracing.TraceContext(trace_id=trace_id, conversation_id=conversation_id)
    logger.info("answer.start", query=req.query[:80], trace_id=trace_id)

    # ── 1. Ordinal 참조 resolve ───────────────────────────────────────────
    effective_query, resolved_title = await context_resolver.resolve_query(
        req.query, redis, conversation_id
    )
    if resolved_title:
        logger.info("answer.resolved", original=req.query[:60], resolved=effective_query[:80])

    # ── 1.5. Conversational Query Rewriting (CQR) ────────────────────────
    recent_turns = await _load_recent_turns(redis, conversation_id)
    last_posts = await context_resolver.load_last_posts(redis, conversation_id)
    router_llm = _build_task_llm(settings, "router")
    t_cqr = time.monotonic()
    rewritten_query, cqr_status = await query_rewriter.contextual_rewrite(
        effective_query, recent_turns, last_posts or None, router_llm
    )
    tc.add_step("cqr", t_cqr, time.monotonic(), {"status": cqr_status})
    cqr_occurred = cqr_status == "rewritten"
    if cqr_occurred:
        logger.info("answer.cqr", original=effective_query[:60], rewritten=rewritten_query[:80])
        effective_query = rewritten_query

    # ── 2. Intent Router ──────────────────────────────────────────────────
    t_s = time.monotonic()
    LLM_CALLS.labels(task="router").inc()
    routing = await intent_router.classify_with_info(
        effective_query, router_llm, recent_turns=recent_turns
    )
    route = routing.intent
    routing_card = RoutingCard(
        intent=str(route),
        method=routing.method,
        reason=routing.reason,
        score=routing.score,
        resolved_query=effective_query if resolved_title else None,
        rewritten_query=rewritten_query if cqr_occurred else None,
    )
    tc.add_step("intent", t_s, time.monotonic(), {"intent": str(route), "method": routing.method})
    logger.info("answer.intent", intent=route, method=routing.method, trace_id=trace_id)

    # ── 3. 거절 정책 ──────────────────────────────────────────────────────
    if route in intent_router.REJECT_INTENTS:
        msg = intent_router.rejection_message(route)
        latency_ms = int((time.monotonic() - t0) * 1000)
        ANSWER_REQUESTS.labels(intent=str(route), status="rejected").inc()
        ANSWER_LATENCY.observe((time.monotonic() - t0))
        asyncio.create_task(tracing.persist(tc, str(route), settings.LMSTUDIO_CHAT_MODEL, latency_ms, "rejected"))
        return MerAnswerResponse(
            trace_id=trace_id,
            conversation_id=conversation_id,
            intent=str(route),
            answer=msg,
            citations=[],
            confidence=0.0,
            verifier=VerifierResult(entailed=False, missing_citations=[]),
            latency_ms=latency_ms,
            model=settings.LMSTUDIO_CHAT_MODEL,
            routing_card=routing_card,
        )

    # ── 4. Blog post list ────────────────────────────────────────────────
    if route == intent_router.IntentRoute.BLOG_POST_LIST:
        t_s = time.monotonic()
        try:
            parsed = blog_post_query.parse_blog_post_list_query(effective_query)
            posts = await blog_post_query.list_blog_posts(session, parsed)
            answer_text = blog_post_query.format_blog_post_list_answer(parsed, posts)
        except Exception as exc:
            logger.error("answer.post_list_error", error=str(exc))
            ANSWER_REQUESTS.labels(intent=str(route), status="error").inc()
            raise HTTPException(status_code=502, detail=f"블로그 글 목록 조회 실패: {exc}") from exc
        tc.add_step(
            "blog_post_list",
            t_s,
            time.monotonic(),
            {"n_posts": len(posts), "basis": parsed.basis, "label": parsed.label},
        )
        # 다음 ordinal 참조를 위해 글 목록을 Redis에 저장
        if conversation_id and posts:
            asyncio.create_task(
                context_resolver.save_last_posts(
                    redis,
                    conversation_id,
                    [
                        {"title": p.title, "url": p.url, "published_at": str(p.published_at)}
                        for p in posts
                    ],
                )
            )
        latency_ms = int((time.monotonic() - t0) * 1000)
        ANSWER_REQUESTS.labels(intent=str(route), status="ok").inc()
        ANSWER_LATENCY.observe((time.monotonic() - t0))
        asyncio.create_task(tracing.persist(tc, str(route), settings.LMSTUDIO_CHAT_MODEL, latency_ms, "ok"))
        return MerAnswerResponse(
            trace_id=trace_id,
            conversation_id=conversation_id,
            intent=str(route),
            answer=answer_text,
            citations=[
                _post_to_citation(post, idx)
                for idx, post in enumerate(posts, start=1)
            ],
            confidence=1.0 if posts else 0.0,
            verifier=VerifierResult(entailed=True, missing_citations=[]),
            latency_ms=latency_ms,
            model=settings.LMSTUDIO_CHAT_MODEL,
            routing_card=routing_card,
        )

    # ── 5. Blog search (keyword) ─────────────────────────────────────────
    if route == intent_router.IntentRoute.BLOG_SEARCH:
        t_s = time.monotonic()
        try:
            keyword = blog_post_query.extract_search_keyword(effective_query)
            posts = await blog_post_query.search_blog_posts(session, keyword)
            answer_text = blog_post_query.format_blog_search_answer(keyword, posts)
        except Exception as exc:
            logger.error("answer.blog_search_error", error=str(exc))
            ANSWER_REQUESTS.labels(intent=str(route), status="error").inc()
            raise HTTPException(status_code=502, detail=f"블로그 글 검색 실패: {exc}") from exc
        tc.add_step(
            "blog_search",
            t_s,
            time.monotonic(),
            {"keyword": keyword, "n_posts": len(posts)},
        )
        if conversation_id and posts:
            asyncio.create_task(
                context_resolver.save_last_posts(
                    redis,
                    conversation_id,
                    [
                        {"title": p.title, "url": p.url, "published_at": str(p.published_at)}
                        for p in posts
                    ],
                )
            )
        latency_ms = int((time.monotonic() - t0) * 1000)
        ANSWER_REQUESTS.labels(intent=str(route), status="ok").inc()
        ANSWER_LATENCY.observe((time.monotonic() - t0))
        asyncio.create_task(tracing.persist(tc, str(route), settings.LMSTUDIO_CHAT_MODEL, latency_ms, "ok"))
        return MerAnswerResponse(
            trace_id=trace_id,
            conversation_id=conversation_id,
            intent=str(route),
            answer=answer_text,
            citations=[
                _post_to_citation(post, idx)
                for idx, post in enumerate(posts, start=1)
            ],
            confidence=1.0 if posts else 0.0,
            verifier=VerifierResult(entailed=True, missing_citations=[]),
            latency_ms=latency_ms,
            model=settings.LMSTUDIO_CHAT_MODEL,
            routing_card=routing_card,
        )

    # ── 6. Smalltalk ─────────────────────────────────────────────────────
    if route == intent_router.IntentRoute.SMALLTALK:
        t_s = time.monotonic()

        # style_pack + 경량 retrieval 병렬 실행
        # — 소식 방법, 건강 질문 등 블로그 글에 관련 내용이 있을 수 있으므로 검색 시도
        style_task = asyncio.create_task(
            style_pack_builder.build(effective_query, top_k=settings.STYLE_TOP_K)
        )
        nodes = []
        try:
            nodes = await _retrieve_nodes(effective_query, max(req.top_k // 2, 5), settings)
        except Exception as exc:
            logger.debug("answer.smalltalk_retrieve_skip", error=str(exc))

        style_pack = await style_task
        evidence = evidence_builder.build(nodes) if nodes else None
        system_p, user_p = prompt_builder.build(
            effective_query, evidence, style_pack=style_pack
        )

        try:
            LLM_CALLS.labels(task="chat").inc()
            answer_text = await response_synthesizer.synthesize(system_p, user_p, llm)
        except Exception as exc:
            LLM_ERRORS.labels(task="chat").inc()
            raise HTTPException(status_code=502, detail=f"LLM 호출 실패: {exc}") from exc

        tc.add_step("chat", t_s, time.monotonic(), {"n_nodes": len(nodes)})
        latency_ms = int((time.monotonic() - t0) * 1000)
        ANSWER_REQUESTS.labels(intent=str(route), status="ok").inc()
        ANSWER_LATENCY.observe((time.monotonic() - t0))
        asyncio.create_task(tracing.persist(tc, str(route), settings.LMSTUDIO_CHAT_MODEL, latency_ms, "ok"))
        return MerAnswerResponse(
            trace_id=trace_id,
            conversation_id=conversation_id,
            intent=str(route),
            answer=answer_text,
            citations=evidence.citations if evidence else [],
            confidence=round(evidence.top_score, 4) if evidence else 1.0,
            verifier=VerifierResult(entailed=True, missing_citations=[]),
            latency_ms=latency_ms,
            model=settings.LMSTUDIO_CHAT_MODEL,
            routing_card=routing_card,
        )

    # ── 6. Retrieve ───────────────────────────────────────────────────────
    t_s = time.monotonic()
    try:
        nodes = await _retrieve_nodes(effective_query, req.top_k, settings, llm=llm)
    except Exception as exc:
        logger.error("answer.retrieve_error", error=str(exc))
        ANSWER_REQUESTS.labels(intent=str(route), status="error").inc()
        raise HTTPException(status_code=502, detail=f"검색 실패: {exc}") from exc
    tc.add_step("retrieve", t_s, time.monotonic(), {"n_nodes": len(nodes)})
    RETRIEVE_NODES.observe(len(nodes))

    # Style pack은 retrieval과 병렬
    style_task = asyncio.create_task(
        style_pack_builder.build(effective_query, top_k=settings.STYLE_TOP_K)
    )

    # ── 6-1. 근거 없음 ────────────────────────────────────────────────────
    if not nodes:
        logger.info("answer.no_evidence", query=effective_query[:80])
        style_pack = await style_task
        system_p, user_p = prompt_builder.build(effective_query, evidence=None, style_pack=style_pack)
        t_s = time.monotonic()
        try:
            LLM_CALLS.labels(task="chat").inc()
            answer_text = await response_synthesizer.synthesize(system_p, user_p, llm)
        except Exception as exc:
            LLM_ERRORS.labels(task="chat").inc()
            raise HTTPException(status_code=502, detail=f"LLM 호출 실패: {exc}") from exc
        tc.add_step("synthesize", t_s, time.monotonic())
        latency_ms = int((time.monotonic() - t0) * 1000)
        ANSWER_REQUESTS.labels(intent=str(route), status="ok").inc()
        ANSWER_LATENCY.observe((time.monotonic() - t0))
        asyncio.create_task(tracing.persist(tc, str(route), settings.LMSTUDIO_CHAT_MODEL, latency_ms, "ok"))
        return MerAnswerResponse(
            trace_id=trace_id,
            conversation_id=conversation_id,
            intent=str(route),
            answer=answer_text,
            citations=[],
            confidence=0.0,
            verifier=VerifierResult(entailed=False, missing_citations=[]),
            latency_ms=latency_ms,
            model=settings.LMSTUDIO_CHAT_MODEL,
            routing_card=routing_card,
        )

    # ── 7. Evidence + Prompt ─────────────────────────────────────────────
    evidence = evidence_builder.build(nodes)
    style_pack = await style_task
    system_p, user_p = prompt_builder.build(effective_query, evidence, style_pack=style_pack)

    # ── 7. Synthesize ─────────────────────────────────────────────────────
    t_s = time.monotonic()
    try:
        LLM_CALLS.labels(task="chat").inc()
        answer_text = await response_synthesizer.synthesize(system_p, user_p, llm)
    except Exception as exc:
        LLM_ERRORS.labels(task="chat").inc()
        ANSWER_REQUESTS.labels(intent=str(route), status="error").inc()
        raise HTTPException(status_code=502, detail=f"LLM 호출 실패: {exc}") from exc
    tc.add_step("synthesize", t_s, time.monotonic(), {"citations": len(evidence.citations)})

    # ── 8. Verify ─────────────────────────────────────────────────────────
    if req.no_verify:
        # eval 모드 등 검증기 스킵 — Qwen verifier LLM 호출 없이 통과
        verify_result = VerifierResult(entailed=True, missing_citations=[])
        logger.info("answer.verify_skipped", trace_id=trace_id)
    else:
        t_s = time.monotonic()
        verifier_llm = _build_task_llm(settings, "verifier")
        LLM_CALLS.labels(task="verifier").inc()
        verify_result = await verifier_svc.verify(answer_text, evidence, verifier_llm)
        tc.add_step("verify", t_s, time.monotonic(), {
            "entailed": verify_result.entailed,
            "missing": verify_result.missing_citations,
        })

    latency_ms = int((time.monotonic() - t0) * 1000)
    ANSWER_REQUESTS.labels(intent=str(route), status="ok").inc()
    ANSWER_LATENCY.observe((time.monotonic() - t0))
    asyncio.create_task(tracing.persist(tc, str(route), settings.LMSTUDIO_CHAT_MODEL, latency_ms, "ok"))

    logger.info(
        "answer.done",
        trace_id=trace_id,
        intent=str(route),
        citations=len(evidence.citations),
        entailed=verify_result.entailed,
        latency_ms=latency_ms,
    )

    return MerAnswerResponse(
        trace_id=trace_id,
        conversation_id=conversation_id,
        intent=str(route),
        answer=answer_text,
        citations=evidence.citations,
        confidence=round(evidence.top_score, 4),
        verifier=verify_result,
        latency_ms=latency_ms,
        model=settings.LMSTUDIO_CHAT_MODEL,
        routing_card=routing_card,
    )


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(
    req: RetrieveRequest,
    settings: Settings = Depends(get_settings),
) -> RetrieveResponse:
    """디버그용 — retrieval 결과만 반환 (LLM 호출 없음)."""
    try:
        nodes = await _retrieve_nodes(req.query, req.top_k, settings)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"검색 실패: {exc}") from exc

    return RetrieveResponse(
        query=req.query,
        nodes=[
            RetrievedNode(
                node_id=n.node.id_,
                text=n.node.get_content()[:300],
                score=float(n.score or 0.0),
                metadata=n.node.metadata,
            )
            for n in nodes
        ],
    )


def _build_task_llm(settings: Settings, task: str) -> OpenAILike:
    from app.shared.llm.lmstudio import build_llm
    return build_llm(settings, task=task)


def _post_to_citation(post: blog_post_query.BlogPostSummary, idx: int) -> Citation:
    published_at = post.published_at.isoformat() if post.published_at is not None else None
    return Citation(
        id=f"p{idx}",
        title=post.title,
        url=post.url,
        published_at=published_at,
        score=1.0,
    )
