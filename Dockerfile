FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY sre_agent.py .
COPY failing_task.py .
COPY reset_demo.py .
COPY static/ static/

# The OTel collector won't be available in cloud — traces go to local SQLite only.
# MCP diagnosis falls back to simulated mode automatically.
# This is fine for the demo — the full loop still runs.

EXPOSE 5000

CMD ["python3", "sre_agent.py", "--serve"]
