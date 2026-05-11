"""Browser chat UI + 메인 인덱스 페이지."""
from __future__ import annotations

from fastapi import APIRouter
from starlette.responses import HTMLResponse, RedirectResponse

from app.mer_persona.core.config import get_settings

router = APIRouter(tags=["ui"])


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index_page() -> HTMLResponse:
    s = get_settings()
    return HTMLResponse(_index_html(git_sha=s.GIT_SHA, build_time=s.BUILD_TIME))


@router.get("/mer/chat", response_class=HTMLResponse, include_in_schema=False)
async def mer_chat_page() -> HTMLResponse:
    return HTMLResponse(
        _chat_page_html(),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


def _index_html(git_sha: str = "local", build_time: str = "unknown") -> str:
    html = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>llm-platform-v2</title>
  <style>
    :root {
      --bg: #f3efe6;
      --panel: #fffaf0;
      --ink: #172018;
      --muted: #6b7068;
      --line: #d8cfbd;
      --accent: #b95b22;
      --accent-dark: #873d16;
      --shadow: 0 24px 80px rgba(45, 38, 25, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: ui-serif, Georgia, "Times New Roman", serif;
      background:
        radial-gradient(circle at top left, rgba(185,91,34,0.18), transparent 34rem),
        linear-gradient(135deg, #efe5d1 0%, #f8f4eb 48%, #ded5c5 100%);
    }
    .wrap {
      max-width: 860px;
      margin: 0 auto;
      padding: 64px 24px 80px;
    }
    .hero { margin-bottom: 56px; }
    .hero h1 {
      margin: 0 0 10px;
      font-size: clamp(28px, 5vw, 44px);
      letter-spacing: -0.04em;
      line-height: 1.1;
    }
    .hero p {
      margin: 0;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.7;
    }
    .section-title {
      margin: 0 0 16px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.10em;
      text-transform: uppercase;
      color: var(--muted);
    }
    .group { margin-bottom: 40px; }
    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
      gap: 14px;
    }
    .card {
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding: 20px 22px;
      border: 1px solid rgba(31,42,36,0.10);
      border-radius: 20px;
      background: rgba(255,250,240,0.75);
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
      text-decoration: none;
      color: inherit;
      transition: transform 0.12s, box-shadow 0.12s;
    }
    .card:hover {
      transform: translateY(-2px);
      box-shadow: 0 32px 96px rgba(45,38,25,0.16);
    }
    .card-icon { font-size: 22px; line-height: 1; }
    .card-title {
      font-size: 15px;
      font-weight: 700;
      letter-spacing: -0.01em;
    }
    .card-url {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 11px;
      color: var(--accent);
    }
    .card-desc { font-size: 13px; color: var(--muted); line-height: 1.55; }
    .api-card { background: rgba(31,42,36,0.04); }
    .badge {
      display: inline-block;
      padding: 1px 8px;
      border-radius: 999px;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.04em;
    }
    .badge-get  { background: #dcfce7; color: #166534; }
    .badge-post { background: #dbeafe; color: #1e40af; }
    footer {
      margin-top: 64px;
      padding-top: 24px;
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: 13px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      display: flex;
      gap: 24px;
      flex-wrap: wrap;
    }
    footer a { color: var(--accent); text-decoration: none; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <h1>llm-platform-v2</h1>
      <p>메르 스타일 금융·경제 QA 플랫폼. 로컬 LLM(LM Studio) 기반 Hybrid RAG.</p>
    </div>

    <!-- UI 페이지 -->
    <div class="group">
      <p class="section-title">UI Pages</p>
      <div class="cards">
        <a class="card" href="/mer/chat">
          <span class="card-icon">💬</span>
          <span class="card-title">MER 챗봇</span>
          <span class="card-url">/mer/chat</span>
          <span class="card-desc">메르 스타일 Hybrid RAG 채팅 인터페이스. Intent routing · 인용 링크 · routing 근거 표시.</span>
        </a>
        <a class="card" href="/ops/batch">
          <span class="card-icon">⚙️</span>
          <span class="card-title">Batch 대시보드</span>
          <span class="card-url">/ops/batch</span>
          <span class="card-desc">배치 수집 현황, Qdrant 상태, 컨테이너 로그 실시간 확인.</span>
        </a>
        <a class="card" href="/ops/eval">
          <span class="card-icon">📊</span>
          <span class="card-title">RAG 품질 평가</span>
          <span class="card-url">/ops/eval</span>
          <span class="card-desc">메르 댓글을 gold로 삼아 생성 답변과의 코사인 유사도·LLM judge 점수 측정.</span>
        </a>
        <a class="card" href="/docs">
          <span class="card-icon">📖</span>
          <span class="card-title">API 문서</span>
          <span class="card-url">/docs</span>
          <span class="card-desc">FastAPI 자동 생성 Swagger UI. 모든 엔드포인트 탐색 및 테스트.</span>
        </a>
      </div>
    </div>

    <!-- API -->
    <div class="group">
      <p class="section-title">API Endpoints</p>
      <div class="cards">
        <a class="card api-card" href="/docs#/mer/answer_v1_mer_answer_post">
          <span class="card-icon">🤖</span>
          <span class="card-title">답변 생성</span>
          <span class="card-url">/v1/mer/answer</span>
          <span class="card-desc"><span class="badge badge-post">POST</span> Hybrid RAG 답변. intent 분류 → 검색 → 합성 → 검증.</span>
        </a>
        <a class="card api-card" href="/docs#/mer/retrieve_v1_mer_retrieve_post">
          <span class="card-icon">🔍</span>
          <span class="card-title">검색 디버그</span>
          <span class="card-url">/v1/mer/retrieve</span>
          <span class="card-desc"><span class="badge badge-post">POST</span> LLM 없이 retrieval 결과만 반환. 검색 품질 점검용.</span>
        </a>
        <a class="card api-card" href="/docs#/mer/chat_v1_mer_chat_post">
          <span class="card-icon">🗨️</span>
          <span class="card-title">대화 채팅</span>
          <span class="card-url">/v1/mer/chat</span>
          <span class="card-desc"><span class="badge badge-post">POST</span> 멀티턴 대화 엔드포인트. 대화 히스토리 Redis 저장.</span>
        </a>
        <a class="card api-card" href="/v1/debug/traces">
          <span class="card-icon">🔬</span>
          <span class="card-title">트레이스 조회</span>
          <span class="card-url">/v1/debug/traces</span>
          <span class="card-desc"><span class="badge badge-get">GET</span> 요청별 단계 실행 시간 및 intent 기록 조회.</span>
        </a>
      </div>
    </div>

    <!-- Ops -->
    <div class="group">
      <p class="section-title">System</p>
      <div class="cards">
        <a class="card api-card" href="/healthz">
          <span class="card-icon">💚</span>
          <span class="card-title">헬스 체크</span>
          <span class="card-url">/healthz</span>
          <span class="card-desc"><span class="badge badge-get">GET</span> 서버 정상 여부 확인.</span>
        </a>
        <a class="card api-card" href="/version">
          <span class="card-icon">🏷️</span>
          <span class="card-title">버전 정보</span>
          <span class="card-url">/version</span>
          <span class="card-desc"><span class="badge badge-get">GET</span> git SHA · 현재 로드된 chat 모델.</span>
        </a>
        <a class="card api-card" href="/metrics">
          <span class="card-icon">📈</span>
          <span class="card-title">Prometheus 메트릭</span>
          <span class="card-url">/metrics</span>
          <span class="card-desc"><span class="badge badge-get">GET</span> 요청 수 · 지연 시간 · LLM 호출 횟수.</span>
        </a>
        <a class="card api-card" href="/ops/logs?container=mer-batch&tail=100">
          <span class="card-icon">📋</span>
          <span class="card-title">컨테이너 로그</span>
          <span class="card-url">/ops/logs</span>
          <span class="card-desc"><span class="badge badge-get">GET</span> mer-batch 컨테이너 최근 로그 JSON.</span>
        </a>
      </div>
    </div>

    <footer>
      <span>llm-platform-v2</span>
      <a href="/docs">Swagger</a>
      <a href="/redoc">ReDoc</a>
      <a href="https://github.com" target="_blank">GitHub</a>
      <span style="margin-left:auto;font-size:11px;opacity:0.7">
        __GIT_SHA__ &nbsp;·&nbsp; __BUILD_TIME__
      </span>
    </footer>
  </div>
</body>
</html>
"""
    return html.replace("__GIT_SHA__", git_sha).replace("__BUILD_TIME__", build_time)


def _chat_page_html() -> str:
    return """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>MER Chat</title>
  <style>
    :root {
      --bg: #f3efe6;
      --panel: #fffaf0;
      --panel-strong: #1f2a24;
      --ink: #172018;
      --muted: #6b7068;
      --line: #d8cfbd;
      --accent: #b95b22;
      --accent-dark: #873d16;
      --user: #1f2a24;
      --assistant: #fffaf0;
      --shadow: 0 24px 80px rgba(45, 38, 25, 0.14);
    }

    * { box-sizing: border-box; }
    html,
    body {
      height: 100%;
    }

    body {
      margin: 0;
      min-height: 100vh;
      overflow: hidden;
      color: var(--ink);
      font-family: ui-serif, Georgia, "Times New Roman", serif;
      background:
        radial-gradient(circle at top left, rgba(185, 91, 34, 0.2), transparent 34rem),
        linear-gradient(135deg, #efe5d1 0%, #f8f4eb 48%, #ded5c5 100%);
    }

    .shell {
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
      gap: 24px;
      width: min(1180px, calc(100% - 32px));
      height: calc(100vh - 48px);
      min-height: 0;
      margin: 24px auto;
    }

    .side,
    .chat {
      border: 1px solid rgba(31, 42, 36, 0.12);
      box-shadow: var(--shadow);
      backdrop-filter: blur(14px);
    }

    .side {
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      min-height: 0;
      overflow: hidden;
      padding: 28px;
      border-radius: 30px;
      background: rgba(255, 250, 240, 0.72);
    }

    .brand {
      margin: 0 0 12px;
      font-size: 34px;
      letter-spacing: -0.04em;
      line-height: 1;
    }

    .desc {
      margin: 0;
      color: var(--muted);
      line-height: 1.65;
      font-size: 15px;
    }

    .status-card {
      margin-top: 28px;
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 20px;
      background: rgba(255, 255, 255, 0.38);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      line-height: 1.7;
    }

    .status-label {
      color: var(--muted);
    }

    .routing-card {
      display: none;
      margin-top: 16px;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 20px;
      background: rgba(255, 255, 255, 0.38);
      font-size: 12px;
      line-height: 1.65;
    }

    .routing-card.visible {
      display: block;
    }

    .routing-title {
      margin: 0 0 10px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
    }

    .routing-intent {
      display: inline-block;
      margin-bottom: 8px;
      padding: 2px 10px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.04em;
      background: var(--accent);
      color: #fffaf0;
    }

    .routing-row {
      display: flex;
      gap: 6px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 11px;
    }

    .routing-key {
      flex-shrink: 0;
      color: var(--muted);
      min-width: 48px;
    }

    .routing-val {
      color: var(--ink);
      word-break: break-word;
    }

    .routing-resolved {
      margin-top: 8px;
      padding: 8px 10px;
      border-radius: 10px;
      background: rgba(185, 91, 34, 0.08);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 11px;
      color: var(--accent-dark);
    }

    .links {
      display: grid;
      gap: 10px;
      margin-top: 24px;
    }

    .links a,
    .ghost {
      display: inline-flex;
      justify-content: center;
      align-items: center;
      min-height: 42px;
      padding: 0 14px;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--ink);
      background: rgba(255, 250, 240, 0.6);
      text-decoration: none;
      cursor: pointer;
    }

    .chat {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      min-height: 0;
      overflow: hidden;
      border-radius: 30px;
      background: rgba(255, 250, 240, 0.88);
    }

    .chat-header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding: 22px 24px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 250, 240, 0.82);
    }

    .chat-title {
      margin: 0;
      font-size: 20px;
      letter-spacing: -0.02em;
    }

    .chat-subtitle {
      margin: 5px 0 0;
      color: var(--muted);
      font-size: 13px;
    }

    .messages {
      min-height: 0;
      overflow-y: auto;
      padding: 24px;
      overscroll-behavior: contain;
    }

    .empty {
      max-width: 560px;
      margin: 12vh auto 0;
      text-align: center;
      color: var(--muted);
      line-height: 1.7;
    }

    .msg {
      display: flex;
      margin: 0 0 16px;
    }

    .msg.user { justify-content: flex-end; }
    .msg.assistant { justify-content: flex-start; }

    .bubble {
      max-width: min(720px, 82%);
      padding: 15px 17px;
      border-radius: 20px;
      line-height: 1.72;
      word-break: break-word;
    }

    .user .bubble {
      color: #f8f4eb;
      background: var(--user);
      border-bottom-right-radius: 6px;
      white-space: pre-wrap;
    }

    .assistant .bubble {
      color: var(--ink);
      background: var(--assistant);
      border: 1px solid var(--line);
      border-bottom-left-radius: 6px;
    }

    /* 어시스턴트 버블 마크다운 스타일 */
    .assistant .bubble h1,
    .assistant .bubble h2,
    .assistant .bubble h3,
    .assistant .bubble h4 {
      margin: 1em 0 0.4em;
      font-size: 1em;
      font-weight: 700;
      letter-spacing: -0.01em;
    }

    .assistant .bubble h1 { font-size: 1.1em; }
    .assistant .bubble h2 { font-size: 1.05em; }

    .assistant .bubble p {
      margin: 0 0 0.75em;
    }

    .assistant .bubble p:last-child {
      margin-bottom: 0;
    }

    .assistant .bubble ul,
    .assistant .bubble ol {
      margin: 0.4em 0 0.75em 1.4em;
      padding: 0;
    }

    .assistant .bubble li {
      margin-bottom: 0.3em;
    }

    .assistant .bubble strong {
      font-weight: 700;
    }

    .assistant .bubble em {
      font-style: italic;
    }

    .assistant .bubble code {
      padding: 1px 5px;
      border-radius: 5px;
      background: rgba(31, 42, 36, 0.08);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.88em;
    }

    .assistant .bubble pre {
      margin: 0.5em 0;
      padding: 12px 14px;
      border-radius: 10px;
      background: rgba(31, 42, 36, 0.06);
      overflow-x: auto;
    }

    .assistant .bubble pre code {
      padding: 0;
      background: none;
      font-size: 0.85em;
    }

    .assistant .bubble blockquote {
      margin: 0.5em 0;
      padding: 0 0 0 12px;
      border-left: 3px solid var(--accent);
      color: var(--muted);
    }

    .assistant .bubble a {
      color: var(--accent);
      text-underline-offset: 2px;
    }

    .assistant .bubble a:hover {
      color: var(--accent-dark);
    }

    .assistant .bubble sup.cite {
      margin: 0 1px 0 2px;
      font-size: 0;       /* 부모 크기 0으로 baseline 간섭 제거 */
      line-height: 0;
      vertical-align: middle;
    }

    .assistant .bubble sup.cite a {
      display: inline-flex !important;
      align-items: center;
      justify-content: center;
      min-width: 1.35em;
      height: 1.35em;
      padding: 0 4px;
      border-radius: 999px;
      color: #fff !important;
      background: #b95b22 !important;
      text-decoration: none !important;
      font-weight: 700;
      font-size: 11px;
      line-height: 1;
      vertical-align: middle;
      cursor: pointer;
    }

    .assistant .bubble sup.cite a:hover {
      background: #873d16 !important;
      color: #fff !important;
    }

    /* 참고자료 접이식 푸터 */
    .assistant .bubble details.cite-refs {
      margin-top: 14px;
      padding-top: 10px;
      border-top: 1px solid var(--line);
      font-size: 12px;
    }
    .assistant .bubble details.cite-refs summary {
      cursor: pointer;
      color: var(--muted);
      font-weight: 600;
      user-select: none;
      list-style: none;
    }
    .assistant .bubble details.cite-refs summary::before {
      content: "▶ ";
      font-size: 10px;
    }
    .assistant .bubble details[open].cite-refs summary::before {
      content: "▼ ";
    }
    .assistant .bubble details.cite-refs ol {
      margin: 8px 0 0;
      padding-left: 20px;
    }
    .assistant .bubble details.cite-refs li {
      margin-bottom: 8px;
      line-height: 1.5;
      color: var(--ink);
    }
    .assistant .bubble details.cite-refs li a {
      color: var(--accent);
      font-weight: 600;
      text-decoration: none;
    }
    .assistant .bubble details.cite-refs li a:hover {
      text-decoration: underline;
    }
    .cite-snippet {
      margin-top: 2px;
      color: var(--muted);
      font-size: 11px;
      font-style: italic;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .assistant .bubble hr {
      margin: 0.75em 0;
      border: none;
      border-top: 1px solid var(--line);
    }

    .meta {
      margin-top: 8px;
      color: var(--muted);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 11px;
    }

    .thinking .bubble {
      color: var(--muted);
      background: rgba(255, 250, 240, 0.58);
      border-style: dashed;
    }

    .phase {
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }

    .spinner {
      width: 10px;
      height: 10px;
      border: 2px solid rgba(185, 91, 34, 0.24);
      border-top-color: var(--accent);
      border-radius: 999px;
      animation: spin 0.8s linear infinite;
    }

    @keyframes spin {
      to { transform: rotate(360deg); }
    }

    .composer {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      padding: 18px;
      border-top: 1px solid var(--line);
      background: rgba(255, 250, 240, 0.94);
    }

    textarea {
      width: 100%;
      min-height: 58px;
      max-height: 180px;
      resize: vertical;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 18px;
      color: var(--ink);
      background: rgba(255, 255, 255, 0.72);
      font: 16px/1.5 ui-serif, Georgia, "Times New Roman", serif;
      outline: none;
    }

    textarea:focus {
      border-color: rgba(185, 91, 34, 0.7);
      box-shadow: 0 0 0 4px rgba(185, 91, 34, 0.12);
    }

    .send {
      min-width: 92px;
      border: 0;
      border-radius: 18px;
      color: #fffaf0;
      background: linear-gradient(180deg, var(--accent), var(--accent-dark));
      font-weight: 700;
      cursor: pointer;
    }

    .send:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }

    @media (max-width: 820px) {
      body {
        overflow: auto;
      }

      .shell {
        grid-template-columns: 1fr;
        height: auto;
        min-height: 0;
        margin: 16px auto;
      }

      .side {
        gap: 18px;
      }

      .chat {
        height: min(76vh, 720px);
        min-height: 520px;
      }

      .composer {
        grid-template-columns: 1fr;
      }

      .send {
        min-height: 48px;
      }
    }
  </style>
</head>
<body>
  <main class="shell">
    <aside class="side">
      <section>
        <h1 class="brand">MER Style Chat</h1>
        <p class="desc">리뉴얼 v2 앱의 같은 포트에서 동작하는 테스트용 챗봇입니다. 메르를 사칭하지 않고, 설명 방식만 참고하도록 설계합니다.</p>
        <div class="status-card">
          <div><span class="status-label">api</span> /v1/mer/answer</div>
          <div><span class="status-label">ui</span> /mer/chat</div>
          <div><span class="status-label">session</span> <span id="sessionText">new</span></div>
          <div><span class="status-label">phase</span> <span id="phaseText">idle</span></div>
        </div>

        <div class="routing-card" id="routingCard">
          <p class="routing-title">라우팅 근거</p>
          <div class="routing-intent" id="routingIntent"></div>
          <div class="routing-row">
            <span class="routing-key">method</span>
            <span class="routing-val" id="routingMethod"></span>
          </div>
          <div class="routing-row">
            <span class="routing-key">reason</span>
            <span class="routing-val" id="routingReason"></span>
          </div>
          <div class="routing-row" id="routingScoreRow" style="display:none">
            <span class="routing-key">score</span>
            <span class="routing-val" id="routingScore"></span>
          </div>
          <div class="routing-resolved" id="routingRewritten" style="display:none"></div>
          <div class="routing-resolved" id="routingResolved" style="display:none"></div>
        </div>
      </section>
      <section class="links">
        <a href="/">← Home</a>
        <a href="/ops/batch">Ops Batch Dashboard</a>
        <button class="ghost" id="resetButton" type="button">대화 초기화</button>
      </section>
      <div id="verBadge" style="
        margin-top:16px;
        font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
        font-size:10px;color:var(--muted);
        background:rgba(0,0,0,0.04);border:1px solid var(--line);
        border-radius:5px;padding:4px 10px;text-align:center;
        opacity:0.7;
      "></div>
    </aside>

    <section class="chat" aria-label="MER style chatbot">
      <header class="chat-header">
        <div>
          <h2 class="chat-title">메르 스타일 테스트</h2>
          <p class="chat-subtitle">Enter 전송, Shift+Enter 줄바꿈</p>
        </div>
      </header>
      <div class="messages" id="messages">
        <div class="empty" id="emptyState">질문을 입력하면 `/v1/mer/answer` API로 요청하고 응답을 이 화면에 표시합니다.</div>
      </div>
      <form class="composer" id="chatForm">
        <textarea id="prompt" name="prompt" placeholder="예: 조선업 전망에 대해 알려줘" autocomplete="off"></textarea>
        <button class="send" id="sendButton" type="submit">전송</button>
      </form>
    </section>
  </main>

  <script>
    // 텍스트 이스케이프 유틸
    function escapeHtml(s) {
      return String(s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    function replaceCitations(html, citations) {
      if (!citations || !citations.length) return html;
      const map = new Map(citations.map((c) => [c.id, c]));
      return html.replace(/\[c(\d+)\]/g, (match, num) => {
        const cite = map.get("c" + num);
        if (!cite || !cite.url) return match;
        let tipText = cite.title || "";
        if (cite.snippet) tipText += " / " + cite.snippet;
        const titleAttr = tipText ? ` title="${escapeHtml(tipText)}"` : "";
        return `<sup class="cite"><a href="${escapeHtml(cite.url)}" target="_blank" rel="noopener noreferrer"${titleAttr}>${num}</a></sup>`;
      });
    }

    // 메르 답변은 마크다운 없음 — 줄바꿈만 <br>로 변환
    function renderMarkdown(text, citations) {
      let html = escapeHtml(text).replace(/\\n/g, "<br>");
      return replaceCitations(html, citations);
    }

    // 버전 뱃지 fetch
    fetch("/version").then(r => r.json()).then(v => {
      const el = document.getElementById("verBadge");
      if (el) el.textContent = (v.git_sha || "local") + "  ·  " + (v.build_time || "unknown");
    }).catch(() => {});

    const SESSION_KEY = "mer_v2_chat_conversation_id";
    const messagesEl = document.getElementById("messages");
    const formEl = document.getElementById("chatForm");
    const promptEl = document.getElementById("prompt");
    const sendButton = document.getElementById("sendButton");
    const resetButton = document.getElementById("resetButton");
    const sessionText = document.getElementById("sessionText");
    const phaseText = document.getElementById("phaseText");
    const routingCard = document.getElementById("routingCard");

    const METHOD_LABEL = { semantic: "임베딩 유사도", heuristic: "규칙 패턴", llm: "LLM 분류" };
    const INTENT_LABEL = {
      blog_evidence: "blog_evidence",
      blog_post_list: "blog_post_list",
      blog_search: "blog_search",
      needs_fresh: "needs_fresh",
      smalltalk: "smalltalk",
      specific_lookup: "specific_lookup",
      internal_db: "internal_db",
    };

    function updateRoutingCard(rc) {
      if (!rc) return;
      routingCard.classList.add("visible");
      document.getElementById("routingIntent").textContent = INTENT_LABEL[rc.intent] || rc.intent;
      document.getElementById("routingMethod").textContent = METHOD_LABEL[rc.method] || rc.method;
      document.getElementById("routingReason").textContent = rc.reason || "-";

      const scoreRow = document.getElementById("routingScoreRow");
      if (rc.score != null) {
        scoreRow.style.display = "flex";
        document.getElementById("routingScore").textContent = rc.score.toFixed(3);
      } else {
        scoreRow.style.display = "none";
      }

      const resolvedEl = document.getElementById("routingResolved");
      const rewrittenEl = document.getElementById("routingRewritten");

      if (rc.rewritten_query) {
        rewrittenEl.style.display = "block";
        rewrittenEl.textContent = "✏ CQR → " + rc.rewritten_query;
      } else {
        rewrittenEl.style.display = "none";
      }

      if (rc.resolved_query) {
        resolvedEl.style.display = "block";
        resolvedEl.textContent = "→ " + rc.resolved_query;
      } else {
        resolvedEl.style.display = "none";
      }
    }

    let conversationId = localStorage.getItem(SESSION_KEY) || "";
    let isSending = false;
    let phaseTimer = null;

    function updateSessionLabel() {
      sessionText.textContent = conversationId ? conversationId.slice(0, 8) + "..." : "new";
    }

    function appendMessage(role, content, meta, citations) {
      document.getElementById("emptyState")?.remove();
      const row = document.createElement("div");
      row.className = "msg " + role;

      const bubble = document.createElement("div");
      bubble.className = "bubble";

      if (role === "assistant") {
        // 마크다운 렌더링 + [cN] 인용을 윗첨자 링크로 (XSS 방지 포함)
        const contentEl = document.createElement("div");
        contentEl.innerHTML = renderMarkdown(content, citations);
        bubble.appendChild(contentEl);

        // 참고자료 접이식 푸터 (스니펫 표시)
        if (citations && citations.length) {
          const refs = document.createElement("details");
          refs.className = "cite-refs";
          const summary = document.createElement("summary");
          summary.textContent = `참고자료 ${citations.length}건`;
          refs.appendChild(summary);
          const ol = document.createElement("ol");
          citations.forEach((c) => {
            const li = document.createElement("li");
            const a = document.createElement("a");
            a.href = c.url;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            a.textContent = c.title || c.url;
            li.appendChild(a);
            if (c.snippet) {
              const snip = document.createElement("div");
              snip.className = "cite-snippet";
              snip.textContent = c.snippet;
              li.appendChild(snip);
            }
            ol.appendChild(li);
          });
          refs.appendChild(ol);
          bubble.appendChild(refs);
        }
      } else {
        bubble.textContent = content;
      }

      if (meta) {
        const metaEl = document.createElement("div");
        metaEl.className = "meta";
        metaEl.textContent = meta;
        bubble.appendChild(metaEl);
      }

      row.appendChild(bubble);
      messagesEl.appendChild(row);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function setPhase(text) {
      phaseText.textContent = text;
    }

    function appendThinking() {
      document.getElementById("emptyState")?.remove();
      const row = document.createElement("div");
      row.className = "msg assistant thinking";
      row.id = "thinkingMessage";

      const bubble = document.createElement("div");
      bubble.className = "bubble";
      bubble.innerHTML = '<span class="phase"><span class="spinner"></span><span id="thinkingText">요청 전송 중...</span></span>';

      row.appendChild(bubble);
      messagesEl.appendChild(row);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      return row;
    }

    function updateThinking(text) {
      setPhase(text);
      const thinkingText = document.getElementById("thinkingText");
      if (thinkingText) {
        thinkingText.textContent = text;
      }
    }

    function clearThinking() {
      if (phaseTimer) {
        clearTimeout(phaseTimer);
        phaseTimer = null;
      }
      document.getElementById("thinkingMessage")?.remove();
      setPhase("idle");
    }

    async function sendPrompt(text) {
      const startedAt = performance.now();
      updateThinking("요청 전송 중...");
      phaseTimer = setTimeout(() => updateThinking("의도 분류 및 조회 경로 판단 중..."), 350);
      const response = await fetch("/v1/mer/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: conversationId || null,
          query: text,
          top_k: 10
        })
      });

      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = payload.detail || "요청 처리 중 오류가 발생했습니다.";
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }

      conversationId = payload.conversation_id || conversationId;
      if (conversationId) {
        localStorage.setItem(SESSION_KEY, conversationId);
      }
      updateSessionLabel();

      const elapsedMs = Math.round(performance.now() - startedAt);
      const trace = payload.trace_id ? "trace=" + payload.trace_id + " · " : "";
      const intent = payload.intent ? "intent=" + payload.intent + " · " : "";
      updateThinking("응답 수신 완료");
      clearThinking();
      appendMessage("assistant", payload.answer || "", trace + intent + elapsedMs + "ms", payload.citations || []);
      updateRoutingCard(payload.routing_card || null);
    }

    formEl.addEventListener("submit", async (event) => {
      event.preventDefault();
      const text = promptEl.value.trim();
      if (!text || isSending) return;

      isSending = true;
      sendButton.disabled = true;
      promptEl.value = "";
      appendMessage("user", text);
      appendThinking();

      try {
        await sendPrompt(text);
      } catch (error) {
        clearThinking();
        appendMessage("assistant", "오류: " + error.message);
      } finally {
        clearThinking();
        isSending = false;
        sendButton.disabled = false;
        promptEl.focus();
      }
    });

    promptEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        // 줄바꿈은 항상 막음 (Shift+Enter 제외)
        event.preventDefault();
        // IME 조합 중(한/중/일 입력)이면 전송 보류 — 조합 완료 후 엔터에서 전송
        if (!event.isComposing) {
          formEl.requestSubmit();
        }
      }
    });

    resetButton.addEventListener("click", () => {
      conversationId = "";
      localStorage.removeItem(SESSION_KEY);
      updateSessionLabel();
      clearThinking();
      messagesEl.innerHTML = '<div class="empty" id="emptyState">새 대화를 시작합니다.</div>';
      promptEl.focus();
    });

    updateSessionLabel();
    promptEl.focus();
  </script>
</body>
</html>
"""
