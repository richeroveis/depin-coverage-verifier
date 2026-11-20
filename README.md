# DePIN Coverage Verifier Intelligent Contract

Production-grade GenLayer Intelligent Contract implementing staked DePIN hardware node uptime and geographic telemetry verification with multi-validator consensus settlement on GenLayer Studionet.

---

## Architecture and Core Design

The contract manages the lifecycle of decentralized physical infrastructure network (DePIN) nodes, epoch-based reward pools, and telemetry validation.

### 1. Discrete 250-bps Grid Consensus
To eliminate validator floating-point divergence and non-determinism during live consensus rounds:
- Raw observed telemetry uptimes are mapped onto a discrete 250-bps grid (41 discrete states between 0 and 10,000 bps).
- Payout amounts, slashing penalties, and coverage bands are deterministically derived from the quantized grid state.
- Live validator consensus in `gl.eq_principle.prompt_comparative` achieves 100% agreement across all evaluating validator nodes.

### 2. Fail-Closed Telemetry Processing
- Validators retrieve public HTTPS telemetry endpoints via `gl.nondet.web.render`.
- If an endpoint times out, encounters an HTTP error, or returns a payload shorter than 32 characters, the contract triggers a fail-closed fallback to `TELEMETRY_UNAVAILABLE_FAIL_CLOSED`.
- In fail-closed state, reward is 0 and slash is 0, protecting honest node operators from upstream network outages without releasing unverified funds.

### 3. Zero-Slash Compliance Invariant
- Whenever observed uptime satisfies or exceeds the registered target (`observed_uptime_bps >= target_uptime_bps`), slashing is mathematically guaranteed to be 0 wei (`slash_wei == 0`).

### 4. Strict Native GEN Custody Conservation
- Native GEN custody balance strictly equals:
  `native_custody_balance == active_node_bonds + sponsor_reward_pool + total_refundable_balances`
- 0-wei stranded residue is maintained across all contract transitions.

### 5. Non-Trapping Soft-Fail Refunds
- All payable methods (`fund_epoch_reward_pool_payable`, `register_depin_node_payable`) credit 100% of attached `gl.message.value` into `self.refundable_balances[caller]` when parameters are invalid or duplicate.
- Funds are never trapped or lost due to validation rejects.

### 6. Pull-Payment Payouts with Safe Fallback
- Entitled balances are withdrawn through `withdraw_refundable_balance()` using `@gl.evm.contract_interface` `IEoaRecipient.emit_transfer`.
- If an external transfer reverts or fails, the user balance is preserved intact in `refundable_balances[caller]`.

---

## On-Chain Deployment Proof

- **Network**: GenLayer Studionet (Chain ID: `61999`)
- **RPC URL**: `https://studio.genlayer.com/api`
- **Contract Address**: `0xe4C1Fb91972DC5AbdcF2298590dc90c526899F92`
- **Deploy Transaction**: `0xf776d3e5c26eea9014b460d7c42179331395bed32da238e83b38b457075c0dbb`
- **Source Code Hash (LF SHA-256)**: `82b4507b9a715fbc79a781b41f71f54460f384a292d3f6629910d6e66bf23f03`
- **Git Release Tag**: `studionet-v1`

### Multi-Signer Accounts
- **Sponsor / Deployer EOA**: `0x154a452b0755EE812014C1405B15D905BA06f9c7`
- **Operator EOA**: `0x90F8bf6A479f320ead074411a4B0e7944Ea8c9C1`

### Live Finalized Transactions

| Stage | Transaction Hash | Status | Result |
| :--- | :--- | :--- | :--- |
| Deploy | `0xf776d3e5c26eea9014b460d7c42179331395bed32da238e83b38b457075c0dbb` | `FINALIZED` | `MAJORITY_AGREE` |
| Step 1: Fund Epoch 1 Pool | `0xd7c56e56e26b8d568a58b3ce28be4b95b72946f0ed369840483901420d24a610` | `FINALIZED` | `MAJORITY_AGREE` |
| Step 2: Soft-Fail Duplicate Pool Funding | `0x61467d21e5dc21475f66314b21eb8b47b17e8640df2320736493b3f05a4dc441` | `FINALIZED` | `MAJORITY_AGREE` |
| Step 3: Withdraw Refundable Balance | `0xbf98bb24ec14717fa15dac9bbf25362bb5a21501351bf10441137de7bb022ae5` | `FINALIZED` | `MAJORITY_AGREE` |
| Step 4: Operator Node Registration | `0xb9e2c44ddba3c1633d43462e45bc748c15e8a0c6221bf317b27c23b0783905a1` | `FINALIZED` | `MAJORITY_AGREE` |
| Step 5: Live Validator Consensus Verification | `0x2554cdd86a4d197cd256b55e13cb4e729892e3fb99dd0e019182d5cfa438fc3c` | `FINALIZED` | `MAJORITY_AGREE` |

---

## State Machine Overview

| State | Permitted Caller | Method | Next State | Custody Effect |
| :--- | :--- | :--- | :--- | :--- |
| Any | Any Sponsor | `fund_epoch_reward_pool_payable` | Epoch `ACTIVE` (or refund) | Value locked in reward pool; duplicate credited to caller refund. |
| Epoch `ACTIVE` | Node Operator | `register_depin_node_payable` | Node `ACTIVE` (or refund) | Node bond locked; excess credited to caller refund. |
| Epoch `ACTIVE` | Any Keeper/Caller | `verify_node_telemetry_epoch` | Record `FINALIZED` | Node rewarded; zero slash on compliance; zero drift. |
| Epoch `EXPIRED` | Original Sponsor | `claim_expired_epoch_refund` | Epoch `EXPIRED_REFUNDED` | 100% unallocated reward pool credited to sponsor refund. |
| Node `ACTIVE` | Node Operator | `deregister_depin_node` | Node `DEREGISTERED` | 100% active bond credited to operator refund. |
| Refund > 0 | Entitled Account | `withdraw_refundable_balance` | Balance = 0 | Native GEN sent to caller EOA. |

---

## Testing and Verification

- **Direct Mode Unit Tests**: 51 comprehensive tests in `tests/test_depin_coverage_verifier_direct.py`.
- **Test Results**: 51 passed in 5.19 seconds (100% pass rate).
- **Linter Status**: `genvm-lint check contracts/depin_coverage_verifier.py` passed with 0 errors and 0 warnings.
- **Invariant Checks**: Accounting invariant validated at every state transition.

### Running Tests Locally
```bash
python -m pytest tests/ -v
```

### Running Linter
```bash
genvm-lint check contracts/depin_coverage_verifier.py
```
