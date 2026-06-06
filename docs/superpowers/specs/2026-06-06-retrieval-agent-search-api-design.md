# Retrieval Agent Search API Design

## Goal

Add an independent search API that can improve answer quality for the current Mer blog RAG system and later support local coding LLM workflows.

This is not a general-purpose search chatbot. It is a bounded retrieval layer that can choose and execute search tools, normalize their results, and synthesize grounded answers with citations.

## Scope

In scope:

- Add an independent `/v1/search/*` API surface.
- Support a bounded Retrieval Agent for integrated search answers.
- Support individual tool test endpoints for web search, market data, and local file search.
- Add structured request/response schemas for plans, tool calls, tool results, answers, and citations.
- Add trace/debug records for planner output, tool calls, latency, failures, and final citations.
- Keep the first implementation bounded by step count, timeout, and result count limits.

Out of scope for the first implementation:

- Fully autonomous unlimited agent loops.
- Direct integration into `/v1/mer/answer`.
- Persistent semantic file indexing.
- Production authentication policy changes.
- Final selection of every future search provider category.

## Existing Context

The current app already has:

- `intent_router` for Mer answer routing.
- task-specific LM Studio model routing in `app/shared/llm/lmstudio.py`.
- Postgres trace tables and debug endpoints.
- Mer blog RAG retrieval through Qdrant, BM25, reranking, and answer synthesis.

The new search API should reuse these patterns where practical, but stay independent from `/v1/mer/answer` at first. That keeps the current Mer pipeline stable while the search agent and tools are tested separately.

## Architecture

The new search feature is organized around a bounded Retrieval Agent.

```text
POST /v1/search/answer
  -> planner local LLM
  -> validated tool-call plan
  -> tool adapters
       web_search
       market_data
       local_file_search
  -> normalized results
  -> optional next step, max 3 steps
  -> answer synthesis with citations
  -> structured trace/debug record
```

The planner may choose one or more tools, but tool execution is always performed by server code after schema validation. The model does not directly access the network or filesystem.

## API Surface

### Integrated Answer

`POST /v1/search/answer`

Purpose:

- Main client-facing endpoint.
- Accept a natural-language query.
- Run a bounded agent loop.
- Return a grounded answer with citations, used tools, tool calls, and a trace id.

Response fields:

- `answer`
- `citations`
- `used_tools`
- `tool_calls`
- `trace_id`
- `latency_ms`
- `confidence`

### Plan Debugging

`POST /v1/search/plan`

Purpose:

- Run only planner/tool selection.
- Do not execute tools.
- Debug local model routing quality.

Response fields:

- `intent`
- `steps`
- `tool_calls`
- `reason`
- `raw_output`
- `validation_errors`

### Individual Tool Tests

`POST /v1/search/tools/web`

- Tests web search directly.
- Input: `query`, `top_k`, optional `recency`.
- Output: normalized web results with title, url, snippet, source, and timestamp fields.

`POST /v1/search/tools/market`

- Tests market data directly.
- Input: `query` or `symbol`.
- Output: provider, symbol, asset type, price, currency, as-of timestamp, and market status.

`POST /v1/search/tools/files`

- Tests local file search directly.
- Input: `query`, `path_scope`, `file_globs`, `top_k`.
- Output: path, line number, snippet, score, and match metadata.

The individual tool endpoints are debug/development APIs in the first version. They should share the same tool adapter code used by `/v1/search/answer`, so failures can be isolated to planner quality or tool behavior.

## Tool Categories

### Web Search

Use for:

- Latest news.
- Public web pages.
- General external information.
- External context that can complement Mer blog answers.

Rules:

- Only cited results can be used as final-answer evidence.
- Include source URL and fetched or published timestamp when available.
- If results are weak or missing, say so instead of inventing details.

### Market Data

Use for:

- Stocks.
- Exchange rates.
- Indexes.
- Crypto prices.

Rules:

- Do not answer current price questions from generic web search.
- Use only configured market data providers.
- Include provider, symbol, price, currency, as-of timestamp, and market status.
- Market data tool wins over web search when a query asks for current prices, rates, or quotes.

Candidate providers to evaluate before implementation:

- TradingView
- Naver Financial
- Google Finance
- A stable finance API if available and acceptable

### Local File Search

Use for:

- Local code search.
- Documentation search.
- Logs and config files.
- Local coding LLM support.

Rules:

- Search only within allowed workspace/path scopes.
- Return path, line number, and snippet.
- Keep result windows bounded.
- Do not let the model provide arbitrary filesystem paths without validation.

The first implementation can use `rg`-style lexical search. Semantic file indexing can be added later if lexical search is insufficient.

## Planner Model

The planner is a local LM Studio model selected through the existing task model pattern. It should use a low temperature and strict JSON output.

Expected behavior:

- Choose valid tools.
- Emit structured tool calls.
- Avoid market-data questions going to web search.
- Avoid file-search questions escaping allowed path scopes.
- Return `unsupported` when no configured tool is appropriate.

Quality controls:

- Strict schema validation.
- Few-shot examples in the planner prompt.
- Retry/repair once on invalid JSON.
- Routing evaluation set with expected tools.
- Trace raw planner output for debugging.

## Agent Loop

The first version uses a bounded loop, not a fully free agent.

Initial defaults:

- `max_steps = 3`
- tool timeout: 5-10 seconds per call
- web results: 5-10
- file results: about 10
- market data result count: provider-defined but normalized to one primary quote when possible

Loop behavior:

1. Planner emits one or more tool calls.
2. Server validates calls against schemas and policy.
3. Server executes tools and normalizes results.
4. Planner may inspect summarized results and request another step if useful.
5. Final answer synthesizer writes an answer from normalized evidence.

The final answer must clearly identify when the system could not find enough evidence.

## Data Model

Core conceptual models:

- `SearchPlan`: planner intent, steps, tool calls, reason, raw output.
- `ToolCall`: tool name, validated input, status, latency, error, result count.
- `SearchResult`: normalized result with type, source, title, url/path, snippet/value, timestamp, score, metadata.
- `SearchCitation`: citation id, source, url/path, title, snippet, timestamp.
- `SearchAnswer`: answer, citations, used tools, trace id, confidence, latency.

The exact Pydantic schema names can follow existing project naming conventions under `app/mer_persona/schemas` or a new search schema package.

## Tracing And Debugging

Search trace records should capture:

- original query
- planner model
- planner raw output
- parsed and validated plan
- selected tools
- tool inputs
- tool latency and timeout
- result count
- representative result title/path/symbol
- validation failures
- retry/repair attempts
- final citations used in the answer

This makes it possible to separate planner failures, tool failures, result quality failures, and answer synthesis failures.

## Error Handling

Planner errors:

- Invalid JSON: retry/repair once.
- Still invalid: return a clear planner validation error for `/plan`; for `/answer`, return unsupported/failed planning response.

Tool errors:

- Timeout: record timeout and continue if other useful results exist.
- Provider failure: record provider error and return partial evidence only when safe.
- No results: return no-evidence response instead of fabricating.

Policy errors:

- Disallowed file path scope: reject the tool call.
- Market query routed to web search: planner prompt should prevent this, and server policy should reroute or reject unsafe evidence use.

Answer synthesis errors:

- Return a 502-style API error similar to existing LLM error behavior.
- Persist trace data before returning the error when possible.

## Testing

Unit tests:

- planner JSON parsing
- planner schema validation
- invalid JSON retry/repair
- market questions select `market_data`
- file queries enforce path scope
- result normalizer behavior
- unsupported query fallback

Tool tests:

- direct web tool endpoint
- direct market tool endpoint
- direct files tool endpoint

Integration tests:

- `/v1/search/plan` returns expected tools for representative queries
- `/v1/search/answer` returns citations and used tools
- mixed query can call multiple tools within max step limit
- tool timeout is surfaced in trace/debug data

Evaluation set:

- 20-30 initial examples across web, market, files, mixed, and unsupported categories.

Example routing expectations:

- "오늘 삼성전자 주가 얼마야?" -> `market_data`
- "최근 HMM 관련 뉴스 찾아줘" -> `web_search`
- "이 프로젝트에서 intent_router가 어디 있어?" -> `local_file_search`
- "메르 블로그에서 조선업 관련 글과 최신 뉴스 같이 정리해줘" -> mixed route in a later phase

## Rollout Plan

Phase 1: Search API and schemas

- Add `/v1/search/*` router.
- Add request/response schemas.
- Add tool adapter interfaces.
- Add planner prompt and parser skeleton.
- Add trace/debug model shape.

Phase 2: Individual tool endpoints

- Implement web search direct endpoint.
- Implement market data direct endpoint after provider selection.
- Implement local file search direct endpoint.
- Add tool-level tests.

Phase 3: Bounded Retrieval Agent

- Implement `/v1/search/plan`.
- Implement `/v1/search/answer`.
- Add max-step loop, schema validation, retry/repair, and answer synthesis.
- Add integration tests and routing eval set.

Phase 4: Reuse by Mer and coding workflows

- Optionally call the search API from `/v1/mer/answer`.
- Reuse local file and web search for local coding LLM workflows.
- Add mixed route evaluation examples.

## Open Decisions

- Web search provider.
- Market data provider.
- Whether local file search starts with only lexical `rg` or includes semantic indexing later.
- Whether planner uses the existing router model or a new task-specific model.
- Whether `/v1/search/tools/*` should be public dev endpoints or internal-only endpoints in deployed environments.

## Current Decision

Proceed with an independent `/v1/search/*` bounded Retrieval Agent design. The first implementation should make each tool independently testable before relying on the integrated agent answer endpoint.

