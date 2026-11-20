# GenLayer Studionet Deployment Proof

## Contract Overview
- **Contract Name**: DePINCoverageVerifier (`contracts/depin_coverage_verifier.py`)
- **Contract Address**: `0xe4C1Fb91972DC5AbdcF2298590dc90c526899F92`
- **Network**: GenLayer Studionet
- **RPC Endpoint**: `https://studio.genlayer.com/api`
- **Chain ID**: 61999
- **Deployed Source Hash (LF SHA-256)**: `7e0e03262203cdf9c12060bbaadf21850b91dbc0e138b4198255aacf9ce0b457`
- **Pinned Runner**: `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`

## Participating Multi-Signer Accounts
- **Sponsor / Funder EOA**: `0x154a452b0755EE812014C1405B15D905BA06f9c7` (Account: `tidex22`)
- **Operator EOA**: `0x90F8bf6A479f320ead074411a4B0e7944Ea8c9C1`

---

## Live Lifecycle Transactions

All transactions finalized on GenLayer Studionet with validator consensus.

| Lifecycle Stage | Transaction Hash | Status | Result | Consensus Details |
| :--- | :--- | :--- | :--- | :--- |
| **0. Deploy Contract** | `0xf776d3e5c26eea9014b460d7c42179331395bed32da238e83b38b457075c0dbb` | `FINALIZED` | `MAJORITY_AGREE` | 3 AGREE, 2 IDLE (5 validators committed) |
| **1. Fund Epoch 1 Pool** | `0xd7c56e56e26b8d568a58b3ce28be4b95b72946f0ed369840483901420d24a610` | `FINALIZED` | `MAJORITY_AGREE` | 3 AGREE, 2 IDLE (5 validators committed) |
| **2. Soft-Fail Duplicate Funding** | `0x61467d21e5dc21475f66314b21eb8b47b17e8640df2320736493b3f05a4dc441` | `FINALIZED` | `MAJORITY_AGREE` | 3 AGREE, 2 IDLE (5 validators committed) |
| **3. Withdraw Refundable Balance** | `0xbf98bb24ec14717fa15dac9bbf25362bb5a21501351bf10441137de7bb022ae5` | `FINALIZED` | `MAJORITY_AGREE` | 3 AGREE, 2 IDLE (5 validators committed) |
| **4. Operator Node Registration** | `0xb9e2c44ddba3c1633d43462e45bc748c15e8a0c6221bf317b27c23b0783905a1` | `FINALIZED` | `MAJORITY_AGREE` | 3 AGREE, 2 IDLE (5 validators committed) |
| **5. Live Telemetry Verification** | `0x2554cdd86a4d197cd256b55e13cb4e729892e3fb99dd0e019182d5cfa438fc3c` | `FINALIZED` | `MAJORITY_AGREE` | 3 AGREE, 2 IDLE (5 validators committed) |

---

## Final On-Chain State Verification

Read directly from contract view methods at address `0xe4C1Fb91972DC5AbdcF2298590dc90c526899F92`:

### 1. Contract Accounting
```json
{
  "active_node_bonds": 1000,
  "invariant_holds": true,
  "native_custody_balance": 51000,
  "residue_wei": 0,
  "sponsor_reward_pool": 25000,
  "total_refundable_balances": 25000
}
```
**Custody Invariant Equation**:
`native_custody_balance (51000) == active_node_bonds (1000) + sponsor_reward_pool (25000) + total_refundable_balances (25000)`
`residue_wei == 0` (Exact 0-wei drift verified on chain)

### 2. Node State (`node-alpha-001`)
```json
{
  "exists": true,
  "hardware_id": "HW-DEPIN-001",
  "last_verified_epoch": 1,
  "lifetime_rewards_wei": 25000,
  "lifetime_slashed_wei": 0,
  "operator": "0x90F8bf6A479f320ead074411a4B0e7944Ea8c9C1",
  "region_code": "US-WEST",
  "registered_at_ts": 1795182027,
  "staked_bond_wei": 1000,
  "status": "VERIFIED",
  "target_uptime_bps": 9500,
  "telemetry_endpoint_url": "https://raw.githubusercontent.com/richeroveis/depin-coverage-verifier/main/telemetry/node_001.json"
}
```

### 3. Verification Record (`node-alpha-001:1`)
```json
{
  "coverage_band": "OPTIMAL_RELAY_BONUS",
  "epoch_id": 1,
  "exists": true,
  "node_id": "node-alpha-001",
  "observed_uptime_bps": 9750,
  "reward_awarded_wei": 25000,
  "settled_at_ts": 1795182065,
  "slash_applied_wei": 0,
  "telemetry_verified": true
}
```
- **Observed Uptime**: 9,750 bps (Quantized on discrete 250-bps grid from raw 9,842 bps telemetry).
- **Zero-Slash Compliance**: Observed (9,750 bps) >= Target (9,500 bps) resulting in 0 slash applied.
- **Coverage Band**: `OPTIMAL_RELAY_BONUS`.
