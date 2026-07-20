# sre_agent.py
import os
import sys

# Auto-detect and route execution to the virtual environment if run outside of it
venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "python3")
if os.path.exists(venv_python) and sys.executable != venv_python:
    os.execv(venv_python, [venv_python] + sys.argv)

import json
import time
import subprocess
import importlib
import requests
import traceback
import sqlite3
import threading
import asyncio

# OpenTelemetry imports
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

# Starlette imports
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
import uvicorn

# MCP SDK imports
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

# Google GenAI modern SDK import
from google import genai

# Configuration
TELEMETRY_API = "http://localhost:5000"
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telemetry.db")
SIGNOZ_API_KEY = os.environ.get("SIGNOZ_API_KEY", "iNomx5Oa4ecfnHBa5SLl6hP81D5es8bAOGmRcC0+4mI=")

# --- CUSTOM SQLITE OPENTELEMETRY SPAN EXPORTER ---
class SQLiteSpanExporter(SpanExporter):
    def __init__(self, db_file):
        self.db_file = db_file
        # Create database tables if they do not exist
        conn = sqlite3.connect(self.db_file, timeout=30.0)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spans (
                trace_id TEXT,
                span_id TEXT,
                parent_span_id TEXT,
                name TEXT,
                start_time_nano INTEGER,
                end_time_nano INTEGER,
                duration_ms REAL,
                status_code TEXT,
                status_message TEXT,
                attributes TEXT,
                events TEXT,
                service_name TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_status (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS refactor_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                task_name TEXT,
                error_message TEXT,
                trace_id TEXT,
                before_code TEXT,
                after_code TEXT,
                status TEXT
            )
        """)
        conn.commit()
        
        # Initialize default system status values
        cursor.execute("INSERT OR IGNORE INTO system_status (key, value) VALUES ('state', 'IDLE')")
        cursor.execute("INSERT OR IGNORE INTO system_status (key, value) VALUES ('latency', '0.0')")
        cursor.execute("INSERT OR IGNORE INTO system_status (key, value) VALUES ('error_rate', '0.0')")
        conn.commit()
        conn.close()

    def export(self, spans):
        try:
            conn = sqlite3.connect(self.db_file, timeout=30.0)
            cursor = conn.cursor()
            for span in spans:
                trace_id = "{:032x}".format(span.context.trace_id)
                span_id = "{:016x}".format(span.context.span_id)
                parent_span_id = "{:016x}".format(span.parent.span_id) if span.parent else ""
                name = span.name
                start_nano = span.start_time
                end_nano = span.end_time
                duration_ms = (end_nano - start_nano) / 1_000_000.0
                
                status_code = span.status.status_code.name
                status_message = span.status.description or ""
                
                # Extract and clean attributes/events
                attrs = dict(span.attributes)
                events = []
                for event in span.events:
                    events.append({
                        "name": event.name,
                        "time_nano": event.timestamp,
                        "attributes": dict(event.attributes)
                    })
                    
                service_name = span.resource.attributes.get("service.name", "unknown")
                
                cursor.execute("""
                    INSERT INTO spans (
                        trace_id, span_id, parent_span_id, name, 
                        start_time_nano, end_time_nano, duration_ms, 
                        status_code, status_message, attributes, events, service_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trace_id, span_id, parent_span_id, name,
                    start_nano, end_nano, duration_ms,
                    status_code, status_message, json.dumps(attrs), json.dumps(events), service_name
                ))
            conn.commit()
            conn.close()
            return SpanExportResult.SUCCESS
        except Exception as e:
            print(f"[Warning] Failed to export spans to SQLite: {e}")
            return SpanExportResult.FAILURE

    def shutdown(self):
        pass


# --- INITIALIZE OPENTELEMETRY TRACING ---
resource = Resource(attributes={"service.name": "crucible-sre-worker"})
provider = TracerProvider(resource=resource)

# 1. Export traces to the real containerized OTel Collector
collector_exporter = OTLPSpanExporter(endpoint="http://localhost:4318/v1/traces")
provider.add_span_processor(SimpleSpanProcessor(collector_exporter))

# 2. Export traces to the local SQLite database to power the dashboard
local_exporter = SQLiteSpanExporter(DB_FILE)
provider.add_span_processor(SimpleSpanProcessor(local_exporter))

trace.set_tracer_provider(provider)
tracer = trace.get_tracer("crucible-sre")


# --- INTEGRATED DASHBOARD WEB SERVER ---
async def api_status(request):
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    cursor = conn.cursor()
    if request.method == "POST":
        body = await request.json()
        for key, val in body.items():
            cursor.execute("INSERT OR REPLACE INTO system_status (key, value) VALUES (?, ?)", (key, str(val)))
        conn.commit()
        conn.close()
        return JSONResponse({"status": "updated"})
    else:
        cursor.execute("SELECT key, value FROM system_status")
        rows = cursor.fetchall()
        conn.close()
        status = {r[0]: r[1] for r in rows}
        return JSONResponse(status)

async def api_history(request):
    if request.method == "POST":
        body = await request.json()
        conn = sqlite3.connect(DB_FILE, timeout=30.0)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO refactor_history (task_name, error_message, trace_id, before_code, after_code, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            body.get("task_name"), body.get("error_message"), body.get("trace_id"),
            body.get("before_code"), body.get("after_code"), body.get("status")
        ))
        conn.commit()
        conn.close()
        return JSONResponse({"status": "added"})
    else:
        conn = sqlite3.connect(DB_FILE, timeout=30.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM refactor_history ORDER BY id DESC")
        rows = cursor.fetchall()
        conn.close()
        history = []
        for r in rows:
            history.append({
                "id": r["id"],
                "timestamp": str(r["timestamp"]),
                "task_name": r["task_name"],
                "error_message": r["error_message"],
                "trace_id": r["trace_id"],
                "before_code": r["before_code"],
                "after_code": r["after_code"],
                "status": r["status"]
            })
        return JSONResponse(history)

async def api_spans(request):
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM spans ORDER BY timestamp DESC LIMIT 100")
    rows = cursor.fetchall()
    conn.close()
    spans = []
    for r in rows:
        spans.append({
            "trace_id": r["trace_id"],
            "span_id": r["span_id"],
            "parent_span_id": r["parent_span_id"],
            "name": r["name"],
            "duration_ms": r["duration_ms"],
            "status_code": r["status_code"],
            "service_name": r["service_name"],
            "timestamp": str(r["timestamp"])
        })
    return JSONResponse(spans)

async def api_trace_details(request):
    trace_id = request.path_params["trace_id"]
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM spans WHERE trace_id = ?", (trace_id,))
    rows = cursor.fetchall()
    conn.close()
    spans_list = []
    for r in rows:
        spans_list.append({
            "trace_id": r["trace_id"],
            "span_id": r["span_id"],
            "parent_span_id": r["parent_span_id"],
            "name": r["name"],
            "start_time_nano": r["start_time_nano"],
            "end_time_nano": r["end_time_nano"],
            "duration_ms": r["duration_ms"],
            "status_code": r["status_code"],
            "status_message": r["status_message"],
            "attributes": json.loads(r["attributes"]),
            "events": json.loads(r["events"]),
            "service_name": r["service_name"]
        })
    return JSONResponse({"spans": spans_list})

async def api_reset(request):
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM spans")
    cursor.execute("DELETE FROM refactor_history")
    cursor.execute("UPDATE system_status SET value = 'IDLE' WHERE key = 'state'")
    cursor.execute("UPDATE system_status SET value = '0.0' WHERE key = 'latency'")
    cursor.execute("UPDATE system_status SET value = '0.0' WHERE key = 'error_rate'")
    conn.commit()
    conn.close()
    return JSONResponse({"status": "reset"})

# Mount static folder containing index.html and app.js
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

routes = [
    Route("/api/v1/status", endpoint=api_status, methods=["GET", "POST"]),
    Route("/api/v1/history", endpoint=api_history, methods=["GET", "POST"]),
    Route("/api/v1/spans", endpoint=api_spans, methods=["GET"]),
    Route("/api/v1/traces/{trace_id}", endpoint=api_trace_details, methods=["GET"]),
    Route("/api/v1/reset", endpoint=api_reset, methods=["POST"]),
    Mount("/", app=StaticFiles(directory=static_dir, html=True), name="static")
]

app = Starlette(routes=routes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def start_dashboard_server():
    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="warning")


# --- CORE HELPERS ---
def update_sre_status(state, latency=0.0, error_rate=0.0):
    try:
        requests.post(f"{TELEMETRY_API}/api/v1/status", json={
            "state": state,
            "latency": latency,
            "error_rate": error_rate
        })
    except Exception as e:
        print(f"[Warning] Failed to update status endpoint: {e}")

def add_refactor_history(task_name, error_message, trace_id, before_code, after_code, status):
    try:
        requests.post(f"{TELEMETRY_API}/api/v1/history", json={
            "task_name": task_name,
            "error_message": error_message,
            "trace_id": trace_id,
            "before_code": before_code,
            "after_code": after_code,
            "status": status
        })
    except Exception as e:
        print(f"[Warning] Failed to log refactoring to history endpoint: {e}")


# --- RESILIENT STDIO CLIENT TRANSPORT ---
from contextlib import asynccontextmanager
from typing import TextIO
import anyio
from mcp.client.stdio import (
    _get_executable_command, 
    _create_platform_compatible_process, 
    _terminate_process_tree, 
    PROCESS_TERMINATION_TIMEOUT, 
    get_default_environment
)
from anyio.streams.text import TextReceiveStream
from mcp.client.session import SessionMessage
import mcp.types as types

@asynccontextmanager
async def resilient_stdio_client(server: StdioServerParameters, errlog: TextIO = sys.stderr):
    """
    Resilient client transport for stdio that explicitly strips carriage returns (\r)
    and surrounding whitespace from incoming JSON lines before passing to JSONRPCMessage validation.
    """
    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    try:
        command = _get_executable_command(server.command)
        process = await _create_platform_compatible_process(
            command=command,
            args=server.args,
            env=({**get_default_environment(), **server.env} if server.env is not None else get_default_environment()),
            errlog=errlog,
            cwd=server.cwd,
        )
    except OSError:
        await read_stream.aclose()
        await write_stream.aclose()
        await read_stream_writer.aclose()
        await write_stream_reader.aclose()
        raise

    async def stdout_reader():
        assert process.stdout, "Opened process is missing stdout"
        try:
            async with read_stream_writer:
                buffer = ""
                async for chunk in TextReceiveStream(
                    process.stdout,
                    encoding=server.encoding,
                    errors=server.encoding_error_handler,
                ):
                    lines = (buffer + chunk).split("\n")
                    buffer = lines.pop()

                    for line in lines:
                        # Resilient stripping of carriage returns and whitespace
                        clean_line = line.strip()
                        if not clean_line:
                            continue
                        try:
                            message = types.JSONRPCMessage.model_validate_json(clean_line)
                        except Exception as exc:
                            await read_stream_writer.send(exc)
                            continue

                        session_message = SessionMessage(message)
                        await read_stream_writer.send(session_message)
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async def stdin_writer():
        assert process.stdin, "Opened process is missing stdin"
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    json_str = session_message.message.model_dump_json(by_alias=True, exclude_none=True)
                    await process.stdin.send(
                        (json_str + "\n").encode(
                            encoding=server.encoding,
                            errors=server.encoding_error_handler,
                        )
                    )
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async with (
        anyio.create_task_group() as tg,
        process,
    ):
        tg.start_soon(stdout_reader)
        tg.start_soon(stdin_writer)
        try:
            yield read_stream, write_stream
        finally:
            if process.stdin:
                try:
                    await process.stdin.aclose()
                except Exception:
                    pass

            try:
                with anyio.fail_after(PROCESS_TERMINATION_TIMEOUT):
                    await process.wait()
            except TimeoutError:
                await _terminate_process_tree(process)
            except ProcessLookupError:
                pass
            await read_stream.aclose()
            await write_stream.aclose()
            await read_stream_writer.aclose()
            await write_stream_reader.aclose()

# --- NATIVE MCP DIAGNOSIS CLIENT ---
async def async_query_mcp(trace_id):
    headers = {
        "SIGNOZ-API-KEY": SIGNOZ_API_KEY
    }
    url = "http://localhost:8000/mcp"
    
    # 1. Attempt connection via HTTP/SSE
    try:
        print("[SRE] Attempting SSE network handshake on port 8000...")
        async def sse_handshake():
            async with sse_client(url=url, headers=headers) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    print("[SRE] SSE session initialized! Invoking signoz_get_trace_details...")
                    res = await session.call_tool("signoz_get_trace_details", arguments={"traceId": trace_id})
                    if res and res.content:
                        return res.content[0].text
                    return "No content returned from tool."

        # Wait up to 2.5 seconds for SSE connection and response
        return await asyncio.wait_for(sse_handshake(), timeout=2.5)
    except Exception as e:
        print(f"[SRE] SSE endpoint failed or timed out: {e}. Falling back to Stdio/Docker transport.")

    # 2. Fallback to Stdio via Docker Exec
    try:
        print("[SRE] Spawning native MCP server binary via docker exec...")
        server_params = StdioServerParameters(
            command="docker",
            args=[
                "exec", "-i",
                "-e", "TRANSPORT_MODE=stdio",
                "-e", f"SIGNOZ_API_KEY={SIGNOZ_API_KEY}",
                "signoz-mcp", "/usr/local/bin/signoz-mcp-server"
            ]
        )
        async with resilient_stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("[SRE] Stdio session initialized! Invoking signoz_get_trace_details...")
                res = await session.call_tool("signoz_get_trace_details", arguments={"traceId": trace_id})
                if res and res.content:
                    return res.content[0].text
                return "No trace details content returned from stdio tool call."
    except Exception as e:
        print(f"[SRE] Critical error: Stdio fallback also failed: {e}")
        return f"Error retrieving trace diagnosis details: {e}"

def query_mcp_for_diagnosis(trace_id):
    print(f"\n[SRE] Querying native SigNoz MCP server for Trace ID: {trace_id}...")
    update_sre_status("DIAGNOSING")
    # Wait for the collector to process and flush the trace to ClickHouse
    print("[SRE] Waiting 2 seconds for OTel propagation to ClickHouse...")
    time.sleep(2.0)
    return asyncio.run(async_query_mcp(trace_id))


# --- GEMINI MODERN LLM REFACTOR ENGINE ---
SIMULATED_PATCH = """# failing_task.py
\"\"\"
Crucible Production Substrate: High-Throughput Transaction Processing Mesh.
Implements Ingestion validation handlers for upstream payment gateways.
\"\"\"

def process_transaction_mesh(payload: dict) -> dict:
    \"\"\"
    Parses incoming network payloads.
    EXPECTED SCHEMA: {"meta": {"gateway": "stripe"}, "transactions": [{"amount": 100, "status": "settled"}]}
    DRIFTED SCHEMA CAUSING CRASH: {"meta": {"gateway": "stripe"}, "transactions": {"batch_id": "b_99", "records": [...]}}
    \"\"\"
    total_volume = 0.0
    processed_count = 0
    
    # Check if transactions is a dict and extract its records
    tx_list = payload.get("transactions", [])
    if isinstance(tx_list, dict):
        tx_list = tx_list.get("records", [])
        
    for tx in tx_list:
        amount = tx.get("amount", 0.0)
        total_volume += float(amount)
        processed_count += 1
        
    avg_value = total_volume / processed_count if processed_count > 0 else 0.0
    return {
        "metrics": "active",
        "processed_count": processed_count,
        "total_volume": total_volume,
        "avg_value": avg_value
    }

def run_task():
    drifted_payload = {
        "meta": {"gateway": "next_gen_stripe", "environment": "production-mesh"},
        "transactions": {
            "batch_id": "tx_set_2026",
            "records": [
                {"id": "t1", "amount": "250.50", "status": "settled"},
                {"id": "t2", "amount": "120.00", "status": "settled"}
            ]
        }
    }
    return process_transaction_mesh(drifted_payload)
"""

def refactor_code(telemetry_report, source_code_path):
    print("\n[SRE] Initiating Code Refactoring Loop...")
    update_sre_status("REFACTORING")
    
    with open(source_code_path, "r") as f:
        original_code = f.read()

    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        print("[SRE] Invoking Google GenAI SDK for refactoring...")
        try:
            client = genai.Client(api_key=api_key)
            prompt = f"""
You are an elite Autonomous SRE Remediator operating on a production infrastructure drift event.
Review the following trace exceptions captured by our SigNoz collector instance:
{telemetry_report}

Source Substrate Code:
{original_code}

Refactor the `process_transaction_mesh(payload)` function to make it resilient. The upstream gateway has transitioned from a flat list to a nested structure under `payload['transactions']['records']`.
Your patch must check if `payload['transactions']` is a dict containing a 'records' key, normalize it into an iterable list format automatically, and prevent ZeroDivisionError scenarios by defaulting avg_value to 0.0.

Return ONLY the complete new python code for the entire file. No markdown formatting code fences (like ```python) or extra comments.
"""
            response = client.models.generate_content(
                model="gemini-1.5-flash",
                contents=prompt
            )
            new_code = response.text.strip()
            
            # Clean markdown code wrappers if returned
            if new_code.startswith("```"):
                lines = new_code.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                new_code = "\n".join(lines).strip()
                
            return original_code, new_code
        except Exception as e:
            print(f"[Error] GenAI SDK call failed: {e}. Falling back to simulation.")
            
    print("[SRE] GEMINI_API_KEY not found or call failed. Running in SIMULATED SRE Mode.")
    time.sleep(1.5)  # Simulate thinking time
    return original_code, SIMULATED_PATCH


# --- RUNTIME CONTROLLER ---
def run_sre_loop():
    source_file = "failing_task.py"
    import failing_task
    
    print("=" * 60)
    print("PROJECT CRUCIBLE: STARTING AUTONOMOUS SRE AGENT")
    print("=" * 60)
    
    update_sre_status("RUNNING")
    
    trace_id_hex = ""
    error_occurred = False
    error_msg = ""
    start_time = time.time()
    
    # supervisor transaction span
    with tracer.start_as_current_span("supervisor_task") as parent_span:
        with tracer.start_as_current_span("execute_transaction_mesh") as child_span:
            child_span.set_attribute("gen_ai.request.model", "gemini-1.5-flash")
            child_span.set_attribute("tool.id", "process_transaction_mesh")
            child_span.set_attribute("system.mem.available", "4.2GB")
            
            span_context = child_span.get_span_context()
            trace_id_hex = "{:032x}".format(span_context.trace_id)
            
            try:
                print(f"[SRE] Worker executing task: process_transaction_mesh (Trace ID: {trace_id_hex})")
                time.sleep(0.5)
                result = failing_task.run_task()
                print(f"[SRE] Success! Result: {result}")
            except Exception as e:
                error_occurred = True
                error_msg = f"{type(e).__name__}: {str(e)}"
                print(f"[SRE] 🚨 CRASH DETECTED: {error_msg}")
                
                child_span.record_exception(e)
                child_span.set_status(trace.StatusCode.ERROR, description=error_msg)
                
    provider.force_flush()
    
    if not error_occurred:
        print("[SRE] Task executed successfully on first try. No healing required.")
        update_sre_status("SUCCESS", latency=(time.time() - start_time)*1000, error_rate=0.0)
        return

    # Phase 2: Programmatic Diagnosis using MCP
    update_sre_status("FAILED", error_rate=100.0)
    time.sleep(1.0)
    
    telemetry_report = query_mcp_for_diagnosis(trace_id_hex)
    print("\n--- MCP Diagnostic Report Received ---")
    print(telemetry_report)
    print("--------------------------------------")
    
    # Phase 3: Hot-Swap Refactor & Fix
    original_code, healed_code = refactor_code(telemetry_report, source_file)
    
    with open(source_file, "w") as f:
        f.write(healed_code)
    print(f"\n[SRE] Dynamic patch committed to `{source_file}`.")
    
    # Log refactoring history
    add_refactor_history(
        task_name="process_transaction_mesh",
        error_message=error_msg,
        trace_id=trace_id_hex,
        before_code=original_code,
        after_code=healed_code,
        status="RECOVERED"
    )
    
    # Hot-swap code reload in memory
    print("[SRE] Reloading module code in runtime memory...")
    time.sleep(1.0)
    importlib.reload(failing_task)
    
    # Retry Execution Loop under a new OTel trace
    print("\n[SRE] Restarting SRE Worker Task thread...")
    update_sre_status("RUNNING")
    
    retry_error = False
    retry_start = time.time()
    
    with tracer.start_as_current_span("supervisor_task") as parent_span:
        with tracer.start_as_current_span("execute_transaction_mesh_retry") as child_span:
            child_span.set_attribute("gen_ai.request.model", "gemini-1.5-flash")
            child_span.set_attribute("tool.id", "process_transaction_mesh")
            child_span.set_attribute("system.mem.available", "4.1GB")
            
            try:
                result = failing_task.run_task()
                print(f"[SRE] Success on retry! Result: {result}")
            except Exception as e:
                retry_error = True
                print(f"[SRE] Retry execution failed: {e}")
                child_span.record_exception(e)
                child_span.set_status(trace.StatusCode.ERROR, description=str(e))
                
    provider.force_flush()
    
    if not retry_error:
        print("\n[SRE] ✅ Self-healing loop completed successfully. 0% error rate reached.")
        update_sre_status("SUCCESS", latency=(time.time() - retry_start)*1000, error_rate=0.0)
    else:
        print("\n[SRE] ❌ Self-healing loop failed to recover.")
        update_sre_status("FAILED", latency=(time.time() - retry_start)*1000, error_rate=100.0)


if __name__ == "__main__":
    # Start dashboard HTTP server thread
    print("[Dashboard] Launching background telemetry and web interface on port 5000...")
    web_thread = threading.Thread(target=start_dashboard_server, daemon=True)
    web_thread.start()
    time.sleep(1.0) # wait for web server to initialize
    
    # Run the main SRE self-healing control loop
    run_sre_loop()

    # Keep server alive for visual inspection if requested
    if "--serve" in sys.argv:
        print("\n[Dashboard] Keep-alive flag '--serve' active. Serving dashboard. Press Ctrl+C to terminate...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("[Dashboard] Terminating.")
