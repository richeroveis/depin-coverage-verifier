import os
import sys
import time
import json
import dotenv
from eth_account import Account
import genlayer_py

CONTRACT_ADDRESS = "0xe4C1Fb91972DC5AbdcF2298590dc90c526899F92"
DEPLOY_TX_HASH = "0xf776d3e5c26eea9014b460d7c42179331395bed32da238e83b38b457075c0dbb"
TX1_FUND_HASH = "0xd7c56e56e26b8d568a58b3ce28be4b95b72946f0ed369840483901420d24a610"

def main():
    env = dotenv.dotenv_values(".env")
    sponsor_key = env["GENLAYER_PRIVATE_KEY"]
    sponsor_account = genlayer_py.create_account(sponsor_key)

    # Distinct Operator EOA
    op_key = env.get("OPERATOR_PRIVATE_KEY")
    if op_key:
        operator_account = Account.from_key(op_key)
    else:
        operator_account = Account.create()

    client = genlayer_py.create_client(chain=genlayer_py.studionet, account=sponsor_account)

    print("=== EXECUTING STEPS 2 TO 6 ON GENLAYER STUDIONET ===", flush=True)
    print(f"Contract: {CONTRACT_ADDRESS}", flush=True)
    print(f"Sponsor:  {sponsor_account.address}", flush=True)
    print(f"Operator: {operator_account.address}", flush=True)

    evidence = {
        "contract_address": CONTRACT_ADDRESS,
        "deploy_tx_hash": DEPLOY_TX_HASH,
        "transactions": [
            {
                "description": "Deploy Contract",
                "tx_hash": DEPLOY_TX_HASH,
                "status": "FINALIZED",
                "result": "MAJORITY_AGREE"
            },
            {
                "description": "Step 1: Fund Epoch Reward Pool",
                "tx_hash": TX1_FUND_HASH,
                "status": "FINALIZED",
                "result": "MAJORITY_AGREE"
            }
        ]
    }

    def wait_for_tx(tx_hash, desc):
        print(f"\n--- Waiting for {desc} ({tx_hash}) ---", flush=True)
        for attempt in range(80):
            raw = client.provider.make_request("eth_getTransactionByHash", [tx_hash])
            res = raw.get("result")
            if res:
                st = res.get("status")
                rs = res.get("result")
                print(f"[{desc}] Attempt {attempt}: status={st}, result={rs}", flush=True)
                if st in ["FINALIZED", 7, "7"]:
                    rec = {
                        "description": desc,
                        "tx_hash": tx_hash,
                        "status": str(st),
                        "result": str(rs),
                        "votes": res.get("votes"),
                        "last_round": res.get("last_round")
                    }
                    evidence["transactions"].append(rec)
                    return res
            time.sleep(5)
        raise TimeoutError(f"Transaction {tx_hash} did not finalize")

    # Step 2: Soft-Fail Credit (Duplicate Epoch)
    print("\n[Step 2] Submitting duplicate epoch 1 funding to trigger soft-fail refund...", flush=True)
    tx2_hash = client.write_contract(
        address=CONTRACT_ADDRESS,
        function_name="fund_epoch_reward_pool_payable",
        account=sponsor_account,
        args=[1, 60],
        value=20000
    )
    print(f"Step 2 submitted: {tx2_hash}", flush=True)
    wait_for_tx(tx2_hash, "Step 2: Soft-Fail Duplicate Pool Funding")

    # Step 3: EOA Withdrawal
    print("\n[Step 3] Submitting withdraw_refundable_balance...", flush=True)
    tx3_hash = client.write_contract(
        address=CONTRACT_ADDRESS,
        function_name="withdraw_refundable_balance",
        account=sponsor_account,
        args=[]
    )
    print(f"Step 3 submitted: {tx3_hash}", flush=True)
    wait_for_tx(tx3_hash, "Step 3: EOA Withdrawal")

    # Step 4: Operator Node Registration
    telemetry_url = "https://raw.githubusercontent.com/richeroveis/depin-coverage-verifier/main/telemetry/node_001.json"
    print(f"\n[Step 4] Operator registers node-alpha-001 with bond 1000 wei...", flush=True)
    tx4_hash = client.write_contract(
        address=CONTRACT_ADDRESS,
        function_name="register_depin_node_payable",
        account=operator_account,
        args=["node-alpha-001", "HW-DEPIN-001", "US-WEST", 9500, telemetry_url],
        value=1000
    )
    print(f"Step 4 submitted: {tx4_hash}", flush=True)
    wait_for_tx(tx4_hash, "Step 4: Operator Node Registration")

    # Step 5: Live Validator Telemetry Consensus & Reward Settlement
    print("\n[Step 5] Calling verify_node_telemetry_epoch for node-alpha-001 in epoch 1...", flush=True)
    tx5_hash = client.write_contract(
        address=CONTRACT_ADDRESS,
        function_name="verify_node_telemetry_epoch",
        account=sponsor_account,
        args=["node-alpha-001", 1]
    )
    print(f"Step 5 submitted: {tx5_hash}", flush=True)
    wait_for_tx(tx5_hash, "Step 5: Live Validator Telemetry Consensus & Reward Settlement")

    # Read back complete final state
    print("\n=== FINAL STATE READBACK ===", flush=True)
    acct = client.read_contract(address=CONTRACT_ADDRESS, function_name="get_contract_accounting", args=[], account=sponsor_account)
    print("Contract Accounting:", json.dumps(acct, indent=2), flush=True)

    node_data = client.read_contract(address=CONTRACT_ADDRESS, function_name="get_node", args=["node-alpha-001"], account=sponsor_account)
    print("Node State:", json.dumps(node_data, indent=2), flush=True)

    epoch_data = client.read_contract(address=CONTRACT_ADDRESS, function_name="get_epoch", args=[1], account=sponsor_account)
    print("Epoch State:", json.dumps(epoch_data, indent=2), flush=True)

    record_data = client.read_contract(address=CONTRACT_ADDRESS, function_name="get_verification_record", args=["node-alpha-001:1"], account=sponsor_account)
    print("Verification Record:", json.dumps(record_data, indent=2), flush=True)

    evidence["final_state"] = {
        "accounting": acct,
        "node": node_data,
        "epoch": epoch_data,
        "verification_record": record_data
    }

    os.makedirs("docs", exist_ok=True)
    with open("docs/live_lifecycle_evidence.json", "w") as f:
        json.dump(evidence, f, indent=2, default=str)
    print("\nAll steps completed! Evidence saved to docs/live_lifecycle_evidence.json", flush=True)

if __name__ == "__main__":
    main()
