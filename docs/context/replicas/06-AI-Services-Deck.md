# Risk GPT — ERPM AI
## the client Confidential

**Replica of:** the AI services platform deck
**Attribution on slides:** ERPM AI — the programme sponsor
**Fidelity:** 🟢 verbatim. Four slides captured.

> **Standing direction:** the AI services platform is a **separate application**. This platform
> **calls it** for AI services; it is not part of this build.

---

## Slide — Risk GPT MCP: Seamless data integration with AI (on prem & cloud)

| | |
|---|---|
| **What is MCP?** | An open industry standard (backed by Anthropic, OpenAI, Google, Microsoft) that lets AI agents securely connect to any data source or tool through a single, universal protocol. |
| **What is the ERPM AI MCP Server?** | A production-ready MCP server with built-in tools, embedded AI intelligence (LLM gateway, semantic discovery, composite tools), deployable on-prem or cloud with RBAC, OAuth, and audit logging. |
| **Why does it matter?** | Eliminates bespoke integration code. Any AI agent discovers and uses tools dynamically at runtime. One server, one protocol, many agents — secure, governed, and scalable. |
| **What can it do today?** | 497 built-in tools (FMP, OpenBB, FRED, Yahoo, SEC EDGAR, CoinGecko, DuckDB), embedded LLM gateway with 6 AI providers, semantic tool discovery, composite tool orchestration, 7 visual creators, full client SDK. |
| **Where is it going?** | Embedded LLM gateway, semantic tool discovery, federated multi-region mesh, built-in RAG pipeline, OpenTelemetry observability, and a plugin marketplace. |

---

## Slide — Risk GPT MCP: Integration Architecture

```
        HOST — AI Application
  ┌──────────────┬──────────────┬──────────────┐
  │ MCP Client 1 │ MCP Client 2 │ MCP Client N │
  └──────┬───────┴──────┬───────┴──────┬───────┘
         ▼              ▼              ▼
     ┌─────────────────────────────────────────┐
     │      MCP Server(s) — JSON-RPC 2.0       │
     └──────┬──────────────┬─────────────┬─────┘
            ▼              ▼             ▼
      ┌───────────┐  ┌────────────┐  ┌──────────┐
      │  Tavily   │  │  Database  │  │  Custom  │
      │  Search   │  │ Analytics  │  │   APIs   │
      └───────────┘  └────────────┘  └──────────┘
```

- **Host:** AI application that manages user interaction and coordinates MCP
  clients
- **Client:** Lightweight session manager — one per server, maintains isolated
  stateful channel
- **Server:** Wraps external capabilities as Tools, Resources, and Prompts

---

## Slide — Risk GPT: Digital Workers (Agents) *(marked "ERPM AI – In Progress")*

**Agent and Digital Workers Architecture** — component block diagram showing how
the central agent orchestrates domain workers, sub-agents, tools, enterprise
data, and governance controls.

**User channel**
- **User / Analyst** — business request
- **Web UI / Chat** — presentation layer, session entry point

**Core orchestration**
- **Agent Server** — request routing, sessions, worker resolution, audit hooks
- **Lead Agent** — reasoning and orchestration; selects worker profile and
  tools; assembles final response
- **Governance and Controls** — worker permissions, data boundaries,
  auditability, oversight, scalability

**Digital workers**
- **Worker Configuration** — prompt, tool access, data scope, mode
- **Market Risk Worker** — counterparty and market analysis
- **Finance Worker** — financial data, filings, reporting
- **Enterprise Risk Worker** — general risk and control analysis
- **Parallel Sub-agents** — focused tasks executed concurrently

**Execution and sources**
- **Tool Execution Layer** — data queries, document reading, Python analysis,
  reporting, integrations
- **Enterprise Data Sources** — structured: CSV, SQL, DuckDB, Parquet;
  unstructured: PDF, Word, Excel
- **External Intelligence** — web research, market data, SEC filings, investor
  relations content
- **Enterprise Applications** — Teams, Outlook, Jira, Confluence, SharePoint,
  Power BI

> *Presentation note (verbatim): The central agent coordinates specialized
> digital workers, which execute analysis through controlled tools, enterprise
> data, and external intelligence under governance controls.*

---

## Slide — High level component view

```
┌──────────────────────────────────────┬──────────────┐
│              Browser                 │ Azure AD SSO │
├──────────────────────────────────────┴──────────────┤
│   UI Server (AWS) — the AI services platform, Finance GPT, Audit GPT │
├─────────────────────────────────────────────────────┤
│              Back End API Service                   │
├──────────────┬──────────┬───────────┬───────────────┤
│    Agent     │ Backend  │    MCP    │  Sharepoint   │
│Orchestration │   Jobs   │  Server   │   Connector   │
├──────────────┼──────────┼───────────┼───────┬───────┤
│ On Prem MCP  │ AWS S3   │  Vector   │Artifacts│Graph│
│    Server    │ Datalake │ Database  │Database │ DB  │
└──────┬───────┴──────────┴───────────┴─────────┴─────┘
       ▼
┌──────────────────────────┐   ┌────────────────────────┐
│   ON PREM DATA SOURCES   │   │  External Data Sources │
│      SDR/RDR/an internal data store      │   │ News, Fed Reserve, OSFI│
└──────────────────────────┘   └────────────────────────┘
```

- UI Server & Services both run in **AWS**
- Backend API service integrates with other AI services such as **AML, QAS,
  Finance**
- Risk GPT has agentic workflow which is modeled after concept of digital
  workers
- An integrated MCP server can access any data source in AWS or external data
  sources
- Additionally, Risk GPT integrates with MCP servers which are hosted **on-prem**
  and they open the client proprietary on prem data to AI agents and chats in Risk GPT
- **Vector searches, documents ingestion are built in backend services**
- Autonomous reasoning on data is built in digital worker platform which provides
  a **near zero code agent creation experience**
