# reset_demo.py
import os
import sys

# Auto-detect and route execution to the virtual environment if run outside of it
venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "python3")
if os.path.exists(venv_python) and sys.executable != venv_python:
    os.execv(venv_python, [venv_python] + sys.argv)

import requests

BUGGY_CODE = """# failing_task.py
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
    
    # BUG: Assumes 'transactions' is a list. Drifted payload presents a dictionary structure.
    # If the upstream gateway updates to a nested dictionary block, this raises an AttributeError or TypeError.
    tx_list = payload.get("transactions", [])
    
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
"""

def main():
    print("[Demo] Resetting failing_task.py to its original buggy version...")
    with open("failing_task.py", "w") as f:
        f.write(BUGGY_CODE)
        
    print("[Demo] Calling telemetry server reset endpoint...")
    try:
        resp = requests.post("http://localhost:5000/api/v1/reset")
        if resp.status_code == 200:
            print("[Demo] ✅ Telemetry database and status have been reset successfully.")
        else:
            print(f"[Demo] ⚠️ Reset endpoint returned status code: {resp.status_code}")
    except Exception as e:
        print(f"[Demo] ℹ️ Telemetry database status was not reset (Dashboard is not active). This is expected on initial run.")
        print("To run the agent and view the dashboard, execute: python3 sre_agent.py --serve")

if __name__ == "__main__":
    main()
