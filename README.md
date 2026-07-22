# Project Crucible — Autonomous Failure Remediation SRE Engine

> "Traditional observability platforms stop after identifying failures. Project Crucible closes the loop by using OpenTelemetry traces to autonomously diagnose, remediate, hot-swap, and verify production failures without manual intervention."

---

## 🚀 Key Architectural Pillars

### 1. Dual-Exporter OpenTelemetry Instrumentation
A single, custom `TracerProvider` exports telemetry data simultaneously:
- **Production Pipeline**: Directs spans to the native OpenTelemetry OTLP endpoint (port `4318`) managed by SigNoz.
- **Local Dashboard Mirror**: Intercepts traces via `TypeSafeSQLiteExporter` to update the real-time visualization UI instantly without CORS restrictions or high database load.

### 2. Native Model Context Protocol (MCP) Integration
- Evaluates active errors by fetching trace contextual metadata directly from SigNoz via MCP (using SSE transport with an automated docker-stdio fallback).
- Processes complete diagnostic reports (raw queries, exceptions, metadata variables).

### 3. Dynamic Runtime Remediation & In-Memory Hot-Swapping
- Sends telemetry trace details to the Gemini core to generate a precise code modification.
- Commits the dynamic patch to the application filesystem.
- Triggers a live module reload in-memory using `importlib.reload()`, verifying the repair under a secondary validation trace without stopping the server.

---

## 🛠️ Getting Started

### 1. Requirements
Ensure you have Docker and python3 installed.

### 2. Telemetry Reset & Bug Injection
Seed the production Gateway Schema Drift incident:
```bash
python3 reset_demo.py
```

### 3. Run SRE Engine & Dashboard
Launch the engine and serve the dashboard:
```bash
python3 sre_agent.py --serve
```
Open `http://localhost:5000` to view the self-healing control loop pipeline in action!

---

## 🤖 AI Assistance & Tool Disclosure
In accordance with the hackathon rules, we hereby declare the use of AI development assistants during this project:
- **AI Coding & Architecture Assistants:** Used ChatGPT and Gemini for code scaffolding, debugging Linux driver stack interactions, refining system prompts, and optimizing dashboard styling.
- **LLM Runtime Models:** Integrated OpenAI / Ollama models within Project Crucible's core SRE supervisor loop for telemetry reasoning and patch generation.
- **Human Authorship:** All architectural design choices, OpenTelemetry pipeline setups, dynamic module reload engineering, and project integrations were directed, verified, and assembled by our team.
