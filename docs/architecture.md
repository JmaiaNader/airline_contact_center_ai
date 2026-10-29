# Architecture Draft

## Architectural style

Use a **modular monolith** first. One Python application is deployed, but UI, business rules, persistence, AI providers, and policy retrieval have separate responsibilities. Split into services only when there is an evidenced operational need.

## Request flow

1. Streamlit captures the question and explicit employee-language selection.
2. Input validation normalizes the request and carries employee language separately from any booking/contact service language.
3. LangGraph routes to a small, allow-listed business tool; tool selection is not permission enforcement.
4. The tool checks authorization and returns typed, bounded data from approved repositories/calculations.
5. RAG may retrieve approved policy chunks and metadata (document ID, version, approval status, source language, page/section).
6. The response layer verifies required evidence/citations and returns a structured response contract.
7. Streamlit renderers display text, tables, and charts from structured data; never execute LLM-generated HTML.
8. Audit events record permitted metadata and outcomes, excluding secrets and unnecessary passenger data.

## Module ownership

- `app/`: Streamlit pages and presentation only.
- `src/config/`: validated configuration and language context.
- `src/database/`: connection lifecycle, repositories, and migrations; no KPI business logic.
- `src/tools/`: narrow, schema-validated entry points for agent use.
- `src/analytics/`: deterministic KPI definitions/calculations and insight rules.
- `src/forecasting/`: forecast training/inference and Erlang C staffing math.
- `src/rag/`: file ingestion, retrieval, and citations for approved policy versions.
- `src/providers/`: provider adapters with one common interface.
- `src/agent/`: graph state, routing, and prompts; no direct arbitrary SQL.
- `src/harness/`: permissions, validation, audit, and evaluations.
- `tests/`: unit, integration, security, and evaluation tests.

## Language model

Keep three fields distinct:

- `employee_language`: answer language selected by the employee.
- `service_language`: passenger or interaction language used to slice queue/SLA/staffing metrics.
- `policy_document_language`: original language of the policy source.

Do not infer the service language from the employee's UI language. Do not silently translate or erase citations.

## Provider portability

Provider selection is configured once in `src/providers/llm_factory.py` when that module is implemented. UI pages and business tools must not instantiate Ollama/OpenAI clients directly. Business rules must work in tests without an LLM.

## Data boundaries

- MySQL stores structured operational data and policy metadata/version status.
- The original policy files remain in `documents/policies/` or an approved document store.
- Embeddings/chunks are stored in a vector store; each retrieved chunk must retain stable source metadata.
- Synthetic data only in developer fixtures until privacy and access controls are reviewed.
