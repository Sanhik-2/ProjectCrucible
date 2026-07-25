"""
Hugging Face Spaces entry point for Project Crucible.
Uses Gradio SDK (free tier) with FastAPI mount to serve the full dashboard + API.
"""
import os
import sys
import json
import time
import importlib
import sqlite3
import threading

# OpenTelemetry imports
from opentelemetry import trace
from opentelemetry.trace.status import Status, StatusCode
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.resources import Resource

import gradio as gr
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# ── Config ────────────────────────────────────────────────────────────────────
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(APP_DIR, "telemetry.db")
STATIC_DIR = os.path.join(APP_DIR, "static")


# ── SQLite Span Exporter (same as sre_agent.py) ──────────────────────────────
class SQLiteSpanExporter(SpanExporter):
    def __init__(self, db_file):
        self.db_file = db_file
        conn = sqlite3.connect(self.db_file, timeout=30.0)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spans (
                trace_id TEXT, span_id TEXT, parent_span_id TEXT, name TEXT,
                start_time_nano INTEGER, end_time_nano INTEGER, duration_ms REAL,
                status_code TEXT, status_message TEXT, attributes TEXT, events TEXT,
                service_name TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_status (key TEXT PRIMARY KEY, value TEXT)
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS refactor_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                task_name TEXT, error_message TEXT, trace_id TEXT,
                before_code TEXT, after_code TEXT, status TEXT
            )
        """)
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
                duration_ms = (span.end_time - span.start_time) / 1_000_000.0
                attrs = dict(span.attributes)
                events = []
                for event in span.events:
                    events.append({"name": event.name, "time_nano": event.timestamp, "attributes": dict(event.attributes)})
                cursor.execute("""
                    INSERT INTO spans (trace_id, span_id, parent_span_id, name,
                        start_time_nano, end_time_nano, duration_ms,
                        status_code, status_message, attributes, events, service_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (trace_id, span_id, parent_span_id, span.name,
                      span.start_time, span.end_time, duration_ms,
                      span.status.status_code.name, span.status.description or "",
                      json.dumps(attrs), json.dumps(events),
                      span.resource.attributes.get("service.name", "unknown")))
            conn.commit()
            conn.close()
            return SpanExportResult.SUCCESS
        except Exception:
            return SpanExportResult.FAILURE

    def shutdown(self):
        pass


# ── Initialize OTel (local SQLite only — no collector in cloud) ───────────────
resource = Resource(attributes={"service.name": "crucible-sre-worker"})
provider = TracerProvider(resource=resource)
local_exporter = SQLiteSpanExporter(DB_FILE)
provider.add_span_processor(SimpleSpanProcessor(local_exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("crucible-sre")


# ── Buggy code & patch (same as sre_agent.py) ────────────────────────────────
RESET_BUGGY_CODE = '''# failing_task.py
"""
Crucible Production Substrate: High-Throughput Transaction Processing Mesh.
Implements Ingestion validation handlers for upstream payment gateways.
"""

def process_transaction_mesh(payload: dict) -> dict:
    """
    Parses incoming network payloads.
    EXPECTED SCHEMA: {"meta": {"gateway": "stripe"}, "transactions": [{"amount": 100, "status": "settled"}]}
    DRIFTED SCHEMA CAUSING CRASH: {"meta": {"gateway": "stripe"}, "transactions": {"batch_id": "b_99", "records": [...]}}
    """
    total_volume = 0.0
    processed_count = 0
    
    # BUG: Assumes 'transactions' is a list. Drifted payload presents a dictionary structure.
    tx_list = payload.get("transactions", [])
    if isinstance(tx_list, dict):
        raise AttributeError("Upstream payload schema mismatch in Payment Ingestion Mesh. Expected: List[Transaction] | Received: Dict/Object wrapper ('str' object has no attribute 'get')")
        
    for tx in tx_list:
        amount = tx.get("amount", 0.0)
        total_volume += float(amount)
        processed_count += 1
        
    avg_value = total_volume / processed_count
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
'''

SIMULATED_PATCH = '''# failing_task.py
"""
Crucible Production Substrate: High-Throughput Transaction Processing Mesh.
Implements Ingestion validation handlers for upstream payment gateways.
"""

def process_transaction_mesh(payload: dict) -> dict:
    """
    Parses incoming network payloads.
    AUTONOMOUS REPAIR: Resolved upstream schema drift (dict wrapper vs list).
    """
    total_volume = 0.0
    processed_count = 0
    
    # AUTONOMOUS REPAIR: Dynamically handle upstream schema drift & dict wrapper
    transactions = payload.get("transactions", [])
    if isinstance(transactions, dict):
        tx_list = transactions.get("records", [])
    else:
        tx_list = transactions
        
    for tx in tx_list:
        if isinstance(tx, dict):
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
'''


# ── SRE Helpers ───────────────────────────────────────────────────────────────
def update_status(state, latency=0.0, error_rate=0.0):
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO system_status (key, value) VALUES ('state', ?)", (state,))
    cursor.execute("INSERT OR REPLACE INTO system_status (key, value) VALUES ('latency', ?)", (str(latency),))
    cursor.execute("INSERT OR REPLACE INTO system_status (key, value) VALUES ('error_rate', ?)", (str(error_rate),))
    conn.commit()
    conn.close()

def add_history(task_name, error_message, trace_id, before_code, after_code, status):
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO refactor_history (task_name, error_message, trace_id, before_code, after_code, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (task_name, error_message, trace_id, before_code, after_code, status))
    conn.commit()
    conn.close()


def buggy_process_transaction_mesh(payload: dict) -> dict:
    raise AttributeError("Upstream payload schema mismatch in Payment Ingestion Mesh. Expected: List[Transaction] | Received: Dict/Object wrapper ('str' object has no attribute 'get')")


# ── SRE Self-Healing Loop ────────────────────────────────────────────────────
def run_sre_loop():
    source_file = os.path.join(APP_DIR, "failing_task.py")

    # Write buggy code
    with open(source_file, "w") as f:
        f.write(RESET_BUGGY_CODE)
    spec = importlib.util.spec_from_file_location("failing_task", source_file)
    failing_task = importlib.util.module_from_spec(spec)
    sys.modules["failing_task"] = failing_task
    spec.loader.exec_module(failing_task)
    failing_task.process_transaction_mesh = buggy_process_transaction_mesh

    print("=" * 60)
    print("PROJECT CRUCIBLE: STARTING AUTONOMOUS SRE AGENT")
    print("=" * 60)

    update_status("RUNNING")
    trace_id_hex = ""
    error_occurred = False
    error_msg = ""
    start_time = time.time()

    with tracer.start_as_current_span("supervisor_task") as parent_span:
        with tracer.start_as_current_span("execute_transaction_mesh") as child_span:
            child_span.set_attribute("gen_ai.request.model", "gemini-1.5-flash")
            child_span.set_attribute("tool.id", "process_transaction_mesh")
            child_span.set_attribute("system.mem.available", "4.2GB")
            trace_id_hex = "{:032x}".format(child_span.get_span_context().trace_id)
            try:
                print(f"[SRE] Worker executing task (Trace ID: {trace_id_hex})")
                time.sleep(0.5)
                result = failing_task.run_task()
            except Exception as e:
                error_occurred = True
                error_msg = f"{type(e).__name__}: {str(e)}"
                print(f"[SRE] 🚨 CRASH DETECTED: {error_msg}")
                child_span.record_exception(e)
                child_span.set_status(Status(StatusCode.ERROR, error_msg))

    provider.force_flush()

    if not error_occurred:
        update_status("SUCCESS", latency=(time.time() - start_time) * 1000)
        return

    # Phase 2: Diagnosis (simulated MCP)
    update_status("FAILED", error_rate=100.0)
    time.sleep(1.0)
    update_status("DIAGNOSING")
    print("[SRE] Diagnosing via simulated MCP...")
    time.sleep(2.0)
    telemetry_report = f"Trace {trace_id_hex}: AttributeError in execute_transaction_mesh"

    # Phase 3: Refactor (simulated)
    update_status("REFACTORING")
    print("[SRE] Generating patch (simulated)...")
    time.sleep(1.5)
    original_code = RESET_BUGGY_CODE
    healed_code = SIMULATED_PATCH

    with open(source_file, "w") as f:
        f.write(healed_code)

    add_history("process_transaction_mesh", error_msg, trace_id_hex, original_code, healed_code, "RECOVERED")

    # Hot-swap reload
    print("[SRE] Hot-swapping module...")
    time.sleep(1.0)
    spec = importlib.util.spec_from_file_location("failing_task", source_file)
    failing_task = importlib.util.module_from_spec(spec)
    sys.modules["failing_task"] = failing_task
    spec.loader.exec_module(failing_task)

    # Retry
    update_status("RUNNING")
    retry_start = time.time()
    retry_error = False

    with tracer.start_as_current_span("supervisor_task"):
        with tracer.start_as_current_span("execute_transaction_mesh_retry") as child_span:
            child_span.set_attribute("gen_ai.request.model", "gemini-1.5-flash")
            child_span.set_attribute("tool.id", "process_transaction_mesh")
            child_span.set_attribute("system.mem.available", "4.1GB")
            try:
                result = failing_task.run_task()
                print(f"[SRE] ✅ Success on retry! Result: {result}")
                child_span.set_status(Status(StatusCode.OK))
            except Exception as e:
                retry_error = True
                child_span.record_exception(e)
                child_span.set_status(Status(StatusCode.ERROR, str(e)))

    provider.force_flush()

    if not retry_error:
        update_status("SUCCESS", latency=(time.time() - retry_start) * 1000, error_rate=0.0)
    else:
        update_status("FAILED", latency=(time.time() - retry_start) * 1000, error_rate=100.0)


# ── FastAPI API routes ────────────────────────────────────────────────────────
api = FastAPI()

@api.get("/api/v1/status")
async def get_status():
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM system_status")
    rows = cursor.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

@api.post("/api/v1/status")
async def post_status(request: Request):
    body = await request.json()
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    cursor = conn.cursor()
    for key, val in body.items():
        cursor.execute("INSERT OR REPLACE INTO system_status (key, value) VALUES (?, ?)", (key, str(val)))
    conn.commit()
    conn.close()
    return {"status": "updated"}

@api.get("/api/v1/spans")
async def get_spans():
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM spans ORDER BY timestamp DESC LIMIT 100")
    rows = cursor.fetchall()
    conn.close()
    return [{
        "trace_id": r["trace_id"], "span_id": r["span_id"],
        "parent_span_id": r["parent_span_id"], "name": r["name"],
        "duration_ms": r["duration_ms"], "status_code": r["status_code"],
        "service_name": r["service_name"], "timestamp": str(r["timestamp"])
    } for r in rows]

@api.get("/api/v1/traces/{trace_id}")
async def get_trace(trace_id: str):
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM spans WHERE trace_id = ?", (trace_id,))
    rows = cursor.fetchall()
    conn.close()
    return {"spans": [{
        "trace_id": r["trace_id"], "span_id": r["span_id"],
        "parent_span_id": r["parent_span_id"], "name": r["name"],
        "start_time_nano": r["start_time_nano"], "end_time_nano": r["end_time_nano"],
        "duration_ms": r["duration_ms"], "status_code": r["status_code"],
        "status_message": r["status_message"],
        "attributes": json.loads(r["attributes"]), "events": json.loads(r["events"]),
        "service_name": r["service_name"]
    } for r in rows]}

@api.get("/api/v1/history")
async def get_history():
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM refactor_history ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [{
        "id": r["id"], "timestamp": str(r["timestamp"]), "task_name": r["task_name"],
        "error_message": r["error_message"], "trace_id": r["trace_id"],
        "before_code": r["before_code"], "after_code": r["after_code"], "status": r["status"]
    } for r in rows]

@api.post("/api/v1/reset")
async def reset():
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM spans")
    cursor.execute("DELETE FROM refactor_history")
    cursor.execute("UPDATE system_status SET value = 'IDLE' WHERE key = 'state'")
    cursor.execute("UPDATE system_status SET value = '0.0' WHERE key = 'latency'")
    cursor.execute("UPDATE system_status SET value = '0.0' WHERE key = 'error_rate'")
    conn.commit()
    conn.close()
    threading.Thread(target=run_sre_loop, daemon=True).start()
    return {"status": "reset"}

# Serve static files
@api.get("/style.css")
async def serve_css():
    return FileResponse(os.path.join(STATIC_DIR, "style.css"), media_type="text/css")

@api.get("/app.js")
async def serve_js():
    return FileResponse(os.path.join(STATIC_DIR, "app.js"), media_type="application/javascript")

@api.get("/")
async def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"), media_type="text/html")


# ── Gradio app (minimal shell — the real UI is the dashboard) ─────────────────
with gr.Blocks(title="Project Crucible — Autonomous SRE Engine") as demo:
    gr.HTML("""
    <div style="text-align:center;padding:10px 0 0 0;">
        <a href="/" target="_blank" style="
            display:inline-block;
            padding:12px 32px;
            background:linear-gradient(135deg,#00e5ff,#7c4dff);
            color:#fff;
            font-weight:700;
            font-size:16px;
            border-radius:8px;
            text-decoration:none;
            letter-spacing:1px;
        ">🔥 OPEN PROJECT CRUCIBLE DASHBOARD</a>
        <p style="color:#aaa;margin-top:8px;font-size:13px;">Click above to launch the full SRE Incident Response Console</p>
    </div>
    """)

# Mount FastAPI routes onto Gradio's app
app = gr.mount_gradio_app(api, demo, path="/gradio")

# Run initial SRE loop on startup
threading.Thread(target=run_sre_loop, daemon=True).start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
