# failing_task.py
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
