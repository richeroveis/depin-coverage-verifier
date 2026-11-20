# Adversarial Security Review: DePIN Coverage Verifier

## 1. State Machine Table

The contract manages epoch reward pools, staked DePIN hardware node lifecycles, and verification settlement records.

| Status / Entity | Permitted Caller | Method | Next Status | Financial Impact |
| :--- | :--- | :--- | :--- | :--- |
| Any | Any Sponsor / Funder | `fund_epoch_reward_pool_payable` | Epoch `ACTIVE` (or soft-fail credit) | Pool credited by `msg.value` if valid; duplicate/sub-threshold credited 100% to `refundable_balances[caller]`. |
| Epoch `ACTIVE` | Node Operator | `register_depin_node_payable` | Node `ACTIVE` (or soft-fail credit) | Node bond locked (`min_node_bond_wei`); excess or invalid parameters credited to `refundable_balances[caller]`. |
| Epoch `ACTIVE` (after close) | Any Caller (Keeper/Sponsor/Operator) | `verify_node_telemetry_epoch` | Verification Record `FINALIZED` | Exact reward credited to operator or slashed into sponsor refundable balance; 0-wei custody drift. |
| Epoch `ACTIVE` (expired / 0 winners) | Original Sponsor | `claim_expired_epoch_refund` | Epoch `EXPIRED_REFUNDED` | 100% remaining unallocated pool credited to sponsor `refundable_balances`. |
| Node `ACTIVE` (after last verified epoch) | Node Operator | `deregister_depin_node` | Node `DEREGISTERED` | 100% active bond credited to operator `refundable_balances`. |
| Any with balance > 0 | Entitled Account | `withdraw_refundable_balance` | Balance = 0 | Native GEN sent via `IEoaRecipient.emit_transfer`; balance restored if external call fails. |

## 2. Liveness and Stuck Fund Analysis

For every state in which native GEN is held in contract custody, deterministic unlock pathways exist:

1. **Sponsor Reward Pools**:
   - If an epoch concludes and receives telemetry verifications, rewards are settled directly to operators.
   - If an epoch receives no verifications, or the epoch grace period elapses (`gl.message_raw["datetime"] > epoch_end + grace_period`), the sponsor can call `claim_expired_epoch_refund(epoch_id)`.
   - The contract transfers 100% of remaining pool funds into `refundable_balances[sponsor]`, preventing permanent lockup.
2. **Operator Staked Bonds**:
   - Staked collateral bonds are tied to the node lifecycle.
   - After participating epochs have settled, the operator calls `deregister_depin_node(node_id)`.
   - The bond is credited to `refundable_balances[operator]` and can be withdrawn immediately.
   - Slashed bond amounts are credited to sponsor refundable balances, maintaining strict balance conservation.
3. **Refundable Balances**:
   - Anyone with unwithdrawn funds can call `withdraw_refundable_balance()` at any time.
   - The contract uses a pull-payment pattern. If an external transfer reverts or runs out of gas, the balance remains credited to `refundable_balances[sender]` without throwing an unhandled exception or permanently stranding funds.

## 3. Race Conditions Between Competing Transitions

1. **Verification vs Expiry Refund**:
   - `verify_node_telemetry_epoch`: Requires `current_time >= epoch.start_time + epoch.duration_seconds`.
   - `claim_expired_epoch_refund`: Requires `current_time >= epoch.start_time + epoch.duration_seconds + epoch.grace_period_seconds`.
   - The grace period creates a non-overlapping window where operators and keepers can submit telemetry verifications before a sponsor can reclaim unspent funds.
   - Once `claim_expired_epoch_refund` executes, `epoch.is_refunded` is set to `True`, which causes any subsequent verification attempts for that epoch to revert cleanly.
2. **Registration vs Verification**:
   - A node must be registered (`node.is_active == True`) and its registration timestamp must precede the epoch window close.
   - Each `(node_id, epoch_id)` pair can only be verified once. `is_epoch_verified(node_id, epoch_id)` enforces replay protection.
3. **Withdrawal vs Re-crediting**:
   - `withdraw_refundable_balance` zeroes `self.refundable_balances[sender]` before attempting external transfer (`IEoaRecipient.emit_transfer`).
   - If the delivery fails, `self.refundable_balances[sender]` is restored to its exact previous value.
   - This state-update ordering prevents reentrancy while safeguarding user funds.

## 4. Accounting Invariants

The contract enforces the following fundamental native GEN conservation invariant:
```
native_custody_balance == active_node_bonds + sponsor_reward_pool + total_refundable_balances
```

1. **Zero Residue Conservation**:
   - Every wei received via `gl.message.value` is accounted for in one of the three custody categories.
   - Slashes and penalties transfer wei strictly between `active_node_bonds` and `sponsor_reward_pool` or `refundable_balances`.
   - When payouts or refunds are withdrawn, `native_custody_balance` and `total_refundable_balances` decrease by identical amounts.
2. **Non-Trapping Soft-Fail Pattern**:
   - In payable methods (`fund_epoch_reward_pool_payable`, `register_depin_node_payable`), parameter validation failures (e.g., duplicate epoch ID, sub-threshold bond) do not trap or burn caller funds.
   - Instead, 100% of the attached `gl.message.value` is credited to `self.refundable_balances[sender]`.
   - The contract emits a soft-fail event and returns an informative status code.

## 5. Input Validation

1. **Identifiers and Strings**:
   - `node_id`, `node_hardware_id`, and `region_code` must be non-empty strings with maximum length limits (64 characters).
   - `telemetry_endpoint_url` must start with `https://` and not exceed 256 characters.
2. **Numerical Parameters**:
   - `target_uptime_bps`: Must be between 1,000 bps (10.00%) and 10,000 bps (100.00%) and must be an exact multiple of 250 bps.
   - `duration_seconds`: Enforces both a floor (10 seconds) and a ceiling (2,592,000 seconds / 30 days).
   - `grace_period_seconds`: Enforces both a floor (10 seconds) and a ceiling (604,800 seconds / 7 days).
   - `min_node_bond_wei`: Must be strictly positive (> 0 wei).

## 6. Consensus Safety

1. **Exact 250-bps Grid Agreement**:
   - Evaluated uptime is quantized to a 250-bps discrete grid (41 total states from 0 to 10,000 bps).
   - Validator non-determinism is eliminated by converting continuous observations into discrete bands before consensus evaluation.
2. **Fail-Closed Telemetry Retrieval**:
   - Validator nodes fetch external telemetry endpoints using `gl.nondet.web.render`.
   - If the HTTP request fails, times out, or returns a payload shorter than 32 characters, the evaluation immediately falls back to `TELEMETRY_UNAVAILABLE_FAIL_CLOSED`.
   - Under this fallback band, the node receives 0 reward and suffers 0 slash penalty, preventing malicious slashing during network outages.
3. **Zero-Slash Invariant**:
   - When observed uptime meets or exceeds target uptime (`observed_uptime_bps >= target_uptime_bps`), `slash_wei` is strictly 0.
   - This invariant is enforced deterministically in mathematical payout computation.
4. **Prompt Injection Resilience**:
   - External JSON telemetry feeds are parsed for structured numeric keys (`uptime_bps`, `timestamp`, `heartbeat_count`).
   - Free-form text fields inside telemetry payloads are ignored and never interpolated into evaluator prompts.

## 7. Review Findings

| ID | Category | Description | Status | Verification Reference |
| :--- | :--- | :--- | :--- | :--- |
| SEC-01 | Accounting | Custody invariant holds across all transitions | FIXED | `test_accounting_invariant_holds_post_fund`, `test_zero_residue_across_full_lifecycle` |
| SEC-02 | Liveness | Expired epoch pools refundable by original sponsor | FIXED | `test_claim_expired_epoch_refund_success`, `test_expired_refund_rejected_before_grace` |
| SEC-03 | Race Condition | Timestamps prevent pre-expiry pool reclaim | FIXED | `test_verify_and_refund_boundary_race` |
| SEC-04 | Consensus | Telemetry failure fails closed without slashing | FIXED | `test_telemetry_fetch_failure_fail_closed`, `test_telemetry_short_body_fail_closed` |
| SEC-05 | Consensus | Discrete 250-bps grid eliminates validator float divergence | FIXED | `test_quantize_uptime_250bps_grid` |
| SEC-06 | Safety | Zero-slash invariant when observed >= target | FIXED | `test_zero_slash_compliance_invariant` |
| SEC-07 | Reentrancy | Pull-payment with failed transfer recovery | FIXED | `test_withdraw_refundable_failure_restores_balance` |
| SEC-08 | Soft-Fail | Non-trapping payable methods credit caller refunds | FIXED | `test_fund_duplicate_epoch_soft_fails_and_credits_refund` |
