import os
import sys
import time
import json
import dotenv
from eth_account import Account
import genlayer_py
from genlayer_py.types import TransactionStatus

CONTRACT_ADDRESS = "0xe4C1Fb91972DC5AbdcF2298590dc90c526899F92"
DEPLOY_TX_HASH = "0xf776d3e5c26eea9014b460d7c42179331395bed32da238e83b38b457075c0dbb"

def run_lifecycle():
    env = dotenv.dotenv_values(".env")
    sponsor_key = env["GENLAYER_PRIVATE_KEY"]
    sponsor_account = genlayer_py.create_account(sponsor_key)

    # Deterministic secondary signer for operator
    operator_account = Account.from_key("0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d")

    client = genlayer_py.create_client(chain=genlayer_py.studionet, account=sponsor_account)

    print("=== LIVE MULTI-SIGNER ON-CHAIN LIFECYCLE ===")
    print(f"Contract Address: {CONTRACT_ADDRESS}")
    print(f"Signer 1 (Sponsor / Deployer): {sponsor_account.address}")
    print(f"Signer 2 (Node Operator):      {operator_account.address}")

    evidence = {
        "contract_address": CONTRACT_ADDRESS,
        "deploy_tx_hash": DEPLOY_TX_HASH,
        "transactions": []
    }

    # Helper to wait for finalized tx
    def wait_for_tx(tx_hash, desc):
        print(f"\n--- Waiting for {desc} ({tx_hash}) ---")
        receipt = client.wait_for_transaction_receipt(
            tx_hash,
            status=TransactionStatus.FINALIZED,
            retries=90,
            interval=3000,
            full_transaction=True
        )
        status_name = receipt.get("status_name") or receipt.get("status")
        result_name = receipt.get("result_name") or receipt.get("result")
        print(f"[{desc}] Status: {status_name}, Result: {result_name}")
        record = {
            "description": desc,
            "tx_hash": tx_hash,
            "status": str(status_name),
            "result": str(result_name),
            "consensus_data": receipt.get("consensus_data")
        }
        evidence["transactions"].append(record)
        return receipt

    # Step 1: Fund Epoch Reward Pool
    print("\n[Step 1] Sponsor funds epoch 1 reward pool (50,000 wei, 60s duration)...")
    tx1_hash = client.write_contract(
        address=CONTRACT_ADDRESS,
        function_name="fund_epoch_reward_pool_payable",
        account=sponsor_account,
        args=[1, 60],
        value=50000
    )
    receipt1 = wait_for_tx(tx1_hash, "Step 1: Fund Epoch Reward Pool")

    # Step 2: Soft-Fail Credit (Duplicate Epoch)
    print("\n[Step 2] Sponsor triggers soft-fail on duplicate epoch 1 (20,000 wei)...")
    tx2_hash = client.write_contract(
        address=CONTRACT_ADDRESS,
        function_name="fund_epoch_reward_pool_payable",
        account=sponsor_account,
        args=[1, 60],
        value=20000
    )
    receipt2 = wait_for_tx(tx2_hash, "Step 2: Soft-Fail Duplicate Pool Funding")

    # Step 3: EOA Withdrawal of Refundable Balance
    print("\n[Step 3] Sponsor withdraws credited refundable balance to EOA...")
    tx3_hash = client.write_contract(
        address=CONTRACT_ADDRESS,
        function_name="withdraw_refundable_balance",
        account=sponsor_account,
        args=[]
    )
    receipt3 = wait_for_tx(tx3_hash, "Step 3: EOA Withdrawal")

    # Step 4: Operator Node Registration
    telemetry_url = "https://raw.githubusercontent.com/richeroveis/depin-coverage-verifier/main/telemetry/node_001.json"
    print(f"\n[Step 4] Operator ({operator_account.address}) registers node-alpha-001 (1,000 wei bond)...")
    tx4_hash = client.write_contract(
        address=CONTRACT_ADDRESS,
        function_name="register_depin_node_payable",
        account=operator_account,
        args=["node-alpha-001", "HW-DEPIN-001", "US-WEST", 9500, telemetry_url],
        value=1000
    )
    receipt4 = wait_for_tx(tx4_hash, "Step 4: Operator Node Registration")

    # Step 5: Wait for Epoch Window Close (60s + buffer)
    print("\n[Step 5] Waiting 70 seconds for epoch window to close on Studionet...")
    for remaining in range(70, 0, -10):
        print(f"Waiting... {remaining}s remaining")
        time.sleep(10)

    # Step 6: Live Validator Telemetry Consensus & Reward Settlement
    print("\n[Step 6] Verifying node-alpha-001 telemetry via live validator consensus...")
    tx6_hash = client.write_contract(
        address=CONTRACT_ADDRESS,
        function_name="verify_node_telemetry_epoch",
        account=operator_account,
        args=["node-alpha-001", 1]
    )
    receipt6 = wait_for_tx(tx6_hash, "Step 6: Live Validator Telemetry Consensus & Reward Settlement")

    # Step 7: Read Back On-Chain State & Invariants
    print("\n=== FINAL ON-CHAIN STATE VERIFICATION ===")
    acct = client.read_contract(address=CONTRACT_ADDRESS, function_name="get_contract_accounting", args=[], account=sponsor_account)
    print("Contract Accounting:", json.dumps(acct, indent=2))

    node_data = client.read_contract(address=CONTRACT_ADDRESS, function_name="get_node", args=["node-alpha-001"], account=sponsor_account)
    print("Node State:", json.dumps(node_data, indent=2))

    epoch_data = client.read_contract(address=CONTRACT_ADDRESS, function_name="get_epoch", args=[1], account=sponsor_account)
    print("Epoch State:", json.dumps(epoch_data, indent=2))

    record_data = client.read_contract(address=CONTRACT_ADDRESS, function_name="get_verification_record", args=["node-alpha-001:1"], account=sponsor_account)
    print("Verification Record:", json.dumps(record_data, indent=2))

    evidence["final_state"] = {
        "accounting": acct,
        "node": node_data,
        "epoch": epoch_data,
        "verification_record": record_data
    }

    os.makedirs("docs", exist_ok=True)
    with open("docs/live_lifecycle_evidence.json", "w") as f:
        json.dump(evidence, f, indent=2, default=str)
    print("\nEvidence saved to docs/live_lifecycle_evidence.json")

if __name__ == "__main__":
    run_lifecycle()
