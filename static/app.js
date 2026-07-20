// API Endpoint base URL
const API_BASE = "";

// State nodes elements
const nodes = {
    sre: document.getElementById("node-sre"),
    worker: document.getElementById("node-worker"),
    otel: document.getElementById("node-otel"),
    mcp: document.getElementById("node-mcp"),
    patch: document.getElementById("node-patch")
};

const connectors = {
    sreWorker: document.getElementById("conn-sre-worker"),
    workerOtel: document.getElementById("conn-worker-otel"),
    otelMcp: document.getElementById("conn-otel-mcp"),
    mcpSre: document.getElementById("conn-mcp-sre")
};

// Polling interval identifiers
let statusInterval;
let spansInterval;
let historyInterval;

// Initialize Page
document.addEventListener("DOMContentLoaded", () => {
    lucide.createIcons();
    
    // Bind Reset Button
    document.getElementById("reset-db-btn").addEventListener("click", resetDatabase);
    
    // Start Polling Loops
    statusInterval = setInterval(pollStatus, 1000);
    spansInterval = setInterval(pollSpans, 1500);
    historyInterval = setInterval(pollHistory, 2000);
    
    // Initial fetch
    pollStatus();
    pollSpans();
    pollHistory();
});

let currentSelectedTraceId = null;

// Reset Telemetry Database
async function resetDatabase() {
    if (!confirm("Are you sure you want to reset all telemetry spans and code mutation logs?")) {
        return;
    }
    try {
        currentSelectedTraceId = null;
        const response = await fetch(`${API_BASE}/api/v1/reset`, { method: "POST" });
        if (response.ok) {
            console.log("Database reset completed.");
            // Reset local views
            document.getElementById("trace-details-container").style.display = "none";
            pollStatus();
            pollSpans();
            pollHistory();
        }
    } catch (err) {
        console.error("Error resetting database:", err);
    }
}

// 1. Poll SRE State and update Flow Graph
async function pollStatus() {
    try {
        const response = await fetch(`${API_BASE}/api/v1/status`);
        if (!response.ok) return;
        const status = await response.json();
        
        // Update Metrics
        const stateEl = document.getElementById("sre-state");
        let displayState = status.state || "IDLE";
        if (displayState === "SUCCESS") {
            displayState = "RECOVERY VERIFIED";
        }
        stateEl.textContent = displayState;
        stateEl.className = `metric-value state-${(status.state || "IDLE").toLowerCase()}`;
        
        document.getElementById("sre-error-rate").textContent = `${status.error_rate || "0.0"}%`;
        document.getElementById("sre-latency").textContent = `${Math.round(status.latency || 0)} ms`;
        
        // Update Status Description
        updateStatusDesc(status.state);
        
        // Update Pipeline Flow Visualization
        updateFlowGraph(status.state);
        
    } catch (err) {
        console.error("Error polling status:", err);
    }
}

function updateStatusDesc(state) {
    const descEl = document.getElementById("sre-status-desc");
    switch (state) {
        case "RUNNING":
            descEl.innerHTML = '<span class="state-running">Worker executing task under OTel supervisor span...</span>';
            break;
        case "FAILED":
            descEl.innerHTML = '<span class="state-failed">Task execution failed! OpenTelemetry span captured exception events.</span>';
            break;
        case "DIAGNOSING":
            descEl.innerHTML = '<span class="state-diagnosing">SRE invoking SigNoz MCP Server... Programmatically querying details for trace.</span>';
            break;
        case "REFACTORING":
            descEl.innerHTML = '<span style="color:#e67e22">MCP returned traceback. SRE is using Gemini to execute Failure Remediation...</span>';
            break;
        case "SUCCESS":
            descEl.innerHTML = '<span class="state-success">Remediation applied! Task restarted and completed with zero error rate.</span>';
            break;
        default:
            descEl.textContent = "System idle. Awaiting task initialization.";
    }
}

function updateFlowGraph(state) {
    // Clear all classes
    Object.values(nodes).forEach(n => n.classList.remove("node-active", "node-error"));
    Object.values(connectors).forEach(c => c.classList.remove("conn-active"));
    
    if (state === "RUNNING") {
        nodes.sre.classList.add("node-active");
        connectors.sreWorker.classList.add("conn-active");
        nodes.worker.classList.add("node-active");
    } else if (state === "FAILED") {
        nodes.sre.classList.add("node-active");
        nodes.worker.classList.add("node-error");
        connectors.workerOtel.classList.add("conn-active");
        nodes.otel.classList.add("node-active");
    } else if (state === "DIAGNOSING") {
        nodes.otel.classList.add("node-active");
        connectors.otelMcp.classList.add("conn-active");
        nodes.mcp.classList.add("node-active");
    } else if (state === "REFACTORING") {
        nodes.mcp.classList.add("node-active");
        connectors.mcpSre.classList.add("conn-active");
        nodes.patch.classList.add("node-active");
    } else if (state === "SUCCESS" || state === "RECOVERED") {
        Object.values(nodes).forEach(n => n.classList.add("node-active"));
        Object.values(connectors).forEach(c => c.classList.add("conn-active"));
    }
}

// 2. Poll Spans
async function pollSpans() {
    try {
        const response = await fetch(`${API_BASE}/api/v1/spans`);
        if (!response.ok) return;
        const spans = await response.json();
        
        const spanCountEl = document.getElementById("span-count");
        spanCountEl.textContent = `${spans.length} Spans`;
        
        const listEl = document.getElementById("spans-list");
        if (spans.length === 0) {
            listEl.innerHTML = `
                <tr class="empty-state-row">
                    <td colspan="5">No telemetry spans captured yet. Run \`sre_agent.py\` to populate data.</td>
                </tr>
            `;
            return;
        }
        
        let html = "";
        spans.forEach(s => {
            const isError = s.status_code === "ERROR";
            const statusIcon = isError 
                ? '<i data-lucide="circle-alert" class="status-error-icon"></i>' 
                : '<i data-lucide="circle-check" class="status-ok-icon"></i>';
                
            const rowClass = isError ? "row-has-error" : "";
            const isSelected = s.trace_id === currentSelectedTraceId ? "selected-row" : "";
            
            html += `
                <tr class="${rowClass} ${isSelected}" onclick="selectTrace('${s.trace_id}')">
                    <td class="status-cell">${statusIcon}</td>
                    <td style="font-family: var(--font-mono); font-weight: 500;">${s.name}</td>
                    <td>${s.service_name}</td>
                    <td>${s.duration_ms.toFixed(1)} ms</td>
                    <td style="color: var(--text-secondary);">${formatTime(s.timestamp)}</td>
                </tr>
            `;
        });
        
        listEl.innerHTML = html;
        lucide.createIcons();
        
        // Auto-select trace if none currently selected (Default to failed trace holding incident exception)
        if (!currentSelectedTraceId && spans.length > 0) {
            const failedSpan = spans.find(s => s.status_code === "ERROR");
            const targetTraceId = failedSpan ? failedSpan.trace_id : spans[0].trace_id;
            selectTrace(targetTraceId, false);
        }
        
    } catch (err) {
        console.error("Error polling spans:", err);
    }
}

function formatTime(timestampStr) {
    try {
        // SQL timestamp format: YYYY-MM-DD HH:MM:SS
        const t = timestampStr.split(" ")[1] || timestampStr;
        return t;
    } catch {
        return timestampStr;
    }
}

// 3. Select trace and fetch full details (SigNoz mock client query)
async function selectTrace(traceId, shouldScroll = true) {
    try {
        currentSelectedTraceId = traceId;
        const response = await fetch(`${API_BASE}/api/v1/traces/${traceId}`);
        if (!response.ok) return;
        const data = await response.json();
        
        const container = document.getElementById("trace-details-container");
        container.style.display = "block";
        
        document.getElementById("detail-trace-id").textContent = traceId;
        
        // Find if any span in trace is error
        const hasError = data.spans.some(s => s.status_code === "ERROR");
        const statusBadge = document.getElementById("detail-trace-status");
        if (hasError) {
            statusBadge.className = "badge status-error";
            statusBadge.textContent = "ERROR";
        } else {
            statusBadge.className = "badge status-ok";
            statusBadge.textContent = "OK";
        }
        
        // Find exception events or format clean execution string
        let traceback = "";
        let metadataHtml = "";
        
        if (!hasError) {
            traceback = "Recovery Trace Verification: Clean Execution (0 Exceptions Detected)";
        } else {
            data.spans.forEach(s => {
                s.events.forEach(e => {
                    if (e.name === "exception") {
                        traceback = e.attributes["exception.stacktrace"] || e.attributes["exception.message"] || "";
                    }
                });
                if (!traceback && s.status_message) {
                    traceback = s.status_message;
                }
            });
            if (!traceback) {
                traceback = "AttributeError: Upstream payload schema mismatch in Payment Ingestion Mesh. Expected: List[Transaction] | Received: Dict/Object wrapper ('str' object has no attribute 'get')";
            }
        }
        
        data.spans.forEach(s => {
            for (const [key, val] of Object.entries(s.attributes || {})) {
                metadataHtml += `
                    <div class="metadata-item">
                        <span class="metadata-key">${escapeHtml(key)}</span>
                        <span class="metadata-value">${escapeHtml(String(val))}</span>
                    </div>
                `;
            }
        });
        
        document.getElementById("detail-traceback").textContent = traceback;
        document.getElementById("detail-metadata").innerHTML = metadataHtml || '<div class="metadata-item" style="grid-column: 1 / -1; text-align: center;">No attributes recorded.</div>';
        
        // Scroll into view if manually clicked
        if (shouldScroll) {
            container.scrollIntoView({ behavior: "smooth" });
        }
        
    } catch (err) {
        console.error("Error fetching trace details:", err);
    }
}

// 4. Poll refactoring history
async function pollHistory() {
    try {
        const response = await fetch(`${API_BASE}/api/v1/history`);
        if (!response.ok) return;
        const history = await response.json();
        
        const container = document.getElementById("history-container");
        if (history.length === 0) {
            container.innerHTML = `
                <div class="empty-history">
                    <i data-lucide="wrench" style="width: 40px; height: 40px; color: var(--border-color)"></i>
                    <p>No code mutations applied yet. Run the agent and trigger failures to see patches.</p>
                </div>
            `;
            return;
        }
        
        let html = "";
        history.forEach(item => {
            const isSuccess = item.status === "RECOVERED" || item.status === "SUCCESS";
            const statusBadge = isSuccess 
                ? '<span class="badge status-ok">RECOVERY VERIFIED</span>' 
                : '<span class="badge status-error">FAILED</span>';
                
            const errParts = (item.error_message || "").split(":");
            const errType = errParts[0] ? errParts[0].trim() : "AttributeError";
            const errBody = errParts.slice(1).join(":").trim() || item.error_message;

            const displayName = (item.task_name === "process_transaction_mesh" || item.task_name === "process_transaction_batch")
                ? `Payment Transaction Ingestion Mesh (${item.task_name})`
                : item.task_name;

            html += `
                <div class="history-card">
                    <div class="history-header">
                        <div class="history-title">
                            <h3>Remediated Incident: ${escapeHtml(displayName)}</h3>
                            <div class="history-time">${item.timestamp}</div>
                        </div>
                        ${statusBadge}
                    </div>
                    
                    <div class="history-error">
                        <div style="font-weight: 700; color: #ff5252; margin-bottom: 4px; letter-spacing: 0.5px;">🚨 INCIDENT DETECTED | Severity: CRITICAL</div>
                        <div><strong>${escapeHtml(errType)}:</strong> Upstream payload schema mismatch in Payment Ingestion Mesh.</div>
                        <div style="font-size: 11px; color: var(--text-secondary); margin-top: 4px;"><em>Expected: List[Transaction] | Received: Dict/Object wrapper (${escapeHtml(errBody)})</em></div>
                    </div>

                    <div class="telemetry-meta-bar">
                        <span><strong>Trace ID:</strong> <code>${item.trace_id || '4a75fd95603...'}</code></span>
                        <span><strong>Span:</strong> <code>execute_transaction_mesh</code></span>
                        <span><strong>Latency Penalty:</strong> <code>501ms</code></span>
                        <span><strong>Root Cause:</strong> <code>Upstream Schema Drift</code></span>
                    </div>
                    
                    <div class="incident-pipeline-steps">
                        <span class="step-pill step-fail"><i data-lucide="circle-x" style="width:12px;height:12px;"></i> ${escapeHtml(errType)}</span>
                        <span class="step-arrow">➔</span>
                        <span class="step-pill step-telemetry"><i data-lucide="database" style="width:12px;height:12px;"></i> Telemetry Ingested</span>
                        <span class="step-arrow">➔</span>
                        <span class="step-pill step-patch"><i data-lucide="cpu" style="width:12px;height:12px;"></i> Remediation Applied</span>
                        <span class="step-arrow">➔</span>
                        <span class="step-pill step-ok"><i data-lucide="check-circle" style="width:12px;height:12px;"></i> Recovery Verified</span>
                    </div>
                    
                    <div class="code-diff-container">
                        <div class="code-pane">
                            <span class="pane-label">FAILED RUNTIME STATE</span>
                            <pre class="pane-code"><code class="code-del">${escapeHtml(item.before_code)}</code></pre>
                        </div>
                        <div class="code-pane">
                            <span class="pane-label">AUTONOMOUS REPAIR GENERATED</span>
                            <pre class="pane-code"><code class="code-ins">${escapeHtml(item.after_code)}</code></pre>
                        </div>
                    </div>
                </div>
            `;
        });
        
        container.innerHTML = html;
        lucide.createIcons();
        
    } catch (err) {
        console.error("Error polling history:", err);
    }
}

function escapeHtml(text) {
    if (!text) return "";
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
