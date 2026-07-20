# failing_task.py
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
