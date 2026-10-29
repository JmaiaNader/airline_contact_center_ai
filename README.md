# Airline Contact Center AI Platform

A new, local-first modular monolith for contact-center analytics, forecasting, policy retrieval, and a tool-grounded chat assistant.

## Non-negotiable boundaries

- This project is independent from any previous project. Do not copy code from an old project without a deliberate review and test.
- The expected MySQL database is `db_Airlines`; this foundation does not create tables or run migrations.
- Do not store real passenger personal data in local development fixtures.
- The LLM explains evidence; Python/SQL calculate authoritative numeric results.
- Employee language and service language are separate fields. Policy-document language is metadata, not the response language.
- Never let the LLM execute arbitrary SQL or write database records directly.

## Initial stack

- Python 3.12
- Streamlit UI
- LangGraph orchestration
- MySQL + SQLAlchemy
- Ollama as the default local LLM provider; OpenAI is optional and configured separately
- ChromaDB for local document retrieval (when RAG is implemented)
- SQL/Python for deterministic KPI calculations; Erlang C and scikit-learn as later modules

## Local setup (Windows PowerShell)

1. Open this folder in VS Code.
2. Verify Python 3.12 is available:

   ```powershell
   py -3.12 --version
   ```

3. Create and activate an isolated environment:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Create your private environment file:

   ```powershell
   Copy-Item .env.example .env
   ```

   Keep passwords and API keys only in `.env`. Never commit it.

5. Run the starter app:

   ```powershell
   streamlit run app/main.py
   ```

This initial app does not require a database connection. That is intentional: database connectivity and schema changes are separate, reviewed steps.

## Planned build sequence

1. Review `docs/architecture.md`, `docs/AGENT_CONTRACT.md`, and `docs/database_schema.md`.
2. Implement and test settings/input validation.
3. Verify MySQL connectivity without mutating data.
4. Review a first migration before running it against `db_Airlines`.
5. Add one deterministic KPI tool, then its UI, tests, and audit event.
6. Add booking lookup, policy RAG, forecasting, and LangGraph orchestration incrementally.
