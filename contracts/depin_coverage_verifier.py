# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *
from dataclasses import dataclass
from datetime import datetime
import json

@gl.evm.contract_interface
class IEoaRecipient:
    class View:
        pass
    class Write:
        pass

# Coverage band string constants
BAND_OPTIMAL: str = "OPTIMAL_RELAY_BONUS"
BAND_STANDARD: str = "STANDARD_UPTIME_PASS"
BAND_DEGRADED: str = "DEGRADED_THROTTLE_PENALTY"
BAND_OFFLINE_SLASH: str = "OFFLINE_SPOOF_SLASH"
BAND_FAIL_CLOSED: str = "TELEMETRY_UNAVAILABLE_FAIL_CLOSED"

# Node operational status
STATUS_ACTIVE: str = "ACTIVE"
STATUS_VERIFIED: str = "VERIFIED"
STATUS_DEGRADED: str = "DEGRADED"
STATUS_SLASHED: str = "SLASHED"
STATUS_UNVERIFIED: str = "UNVERIFIED"

# Window validation bounds (in seconds)
MIN_EPOCH_DURATION: int = 60          # 1 minute floor
MAX_EPOCH_DURATION: int = 2592000     # 30 days ceiling

# Grid step
GRID_STEP_BPS: int = 250
MIN_TARGET_BPS: int = 250
MAX_TARGET_BPS: int = 10000

@allow_storage
@dataclass
class DePINNode:
    operator: Address
    hardware_id: str
    region_code: str
    target_uptime_bps: u256
    telemetry_endpoint_url: str
    staked_bond_wei: u256
    registered_at_ts: u256
    status: str
    last_verified_epoch: u256
    lifetime_rewards_wei: u256
    lifetime_slashed_wei: u256

@allow_storage
@dataclass
class EpochRewardPool:
    epoch_id: u256
    sponsor: Address
    reward_pool_wei: u256
    initial_pool_wei: u256
    start_time_ts: u256
    end_time_ts: u256
    settled: bool
    settled_node_count: u256

@allow_storage
@dataclass
class EpochVerificationRecord:
    node_id: str
    epoch_id: u256
    observed_uptime_bps: u256
    coverage_band: str
    telemetry_verified: bool
    reward_awarded_wei: u256
    slash_applied_wei: u256
    settled_at_ts: u256

class DePINCoverageVerifier(gl.Contract):
    # Accounting invariants (Rule 3 & 8)
    # Invariant: native_custody_balance == active_node_bonds + sponsor_reward_pool + total_refundable_balances
    native_custody_balance: u256
    active_node_bonds: u256
    sponsor_reward_pool: u256
    total_refundable_balances: u256

    # Minimum bond floor
    min_node_bond_wei: u256

    # Storage mappings
    nodes: TreeMap[str, DePINNode]
    node_ids: DynArray[str]
    epochs: TreeMap[u256, EpochRewardPool]
    epoch_ids: DynArray[u256]
    verification_records: TreeMap[str, EpochVerificationRecord]
    refundable_balances: TreeMap[Address, u256]

    def __init__(self, min_node_bond_wei: u256):
        if min_node_bond_wei == 0:
            raise gl.vm.UserError("min_node_bond_wei must be positive")
        self.min_node_bond_wei = min_node_bond_wei
        self.native_custody_balance = u256(0)
        self.active_node_bonds = u256(0)
        self.sponsor_reward_pool = u256(0)
        self.total_refundable_balances = u256(0)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------
    def _get_consensus_time(self) -> int:
        try:
            raw_dt = gl.message_raw.get("datetime")
            if isinstance(raw_dt, (int, float)):
                return int(raw_dt)
            if isinstance(raw_dt, str):
                s = raw_dt.replace("Z", "+00:00")
                return int(datetime.fromisoformat(s).timestamp())
        except Exception:
            pass
        return 0

    def _credit_refundable(self, account: Address, amount: u256) -> None:
        if amount == 0:
            return
        if not isinstance(account, Address):
            account = Address(account)
        if account in self.refundable_balances:
            self.refundable_balances[account] = self.refundable_balances[account] + amount
        else:
            self.refundable_balances[account] = amount
        self.total_refundable_balances += amount

    def _quantize_uptime_bps(self, raw_bps: int) -> int:
        if raw_bps <= 0:
            return 0
        if raw_bps >= 10000:
            return 10000
        return (raw_bps // GRID_STEP_BPS) * GRID_STEP_BPS

    def _compute_node_state(
        self,
        observed_bps: int,
        target_bps: int,
        telemetry_verified: bool,
        bond_wei: int,
        pool_share_wei: int,
    ) -> tuple[str, str, int, int]:
        """
        Shared node evaluation helper (Rule 5 & 6 & 7).
        Enforces zero slash whenever observed_bps >= target_bps.
        Returns: (coverage_band, status, reward_wei, slash_wei)
        """
        if not telemetry_verified:
            return (BAND_FAIL_CLOSED, STATUS_UNVERIFIED, 0, 0)

        if observed_bps >= target_bps:
            # Zero slash invariant guaranteed
            if observed_bps >= 9750:
                band = BAND_OPTIMAL
                status = STATUS_VERIFIED
                reward = pool_share_wei
                slash = 0
            else:
                band = BAND_STANDARD
                status = STATUS_VERIFIED
                # 80 percent of base share for standard pass
                reward = (pool_share_wei * 80) // 100
                slash = 0
        else:
            # Underperformed target
            half_target = target_bps // 2
            if observed_bps >= half_target:
                band = BAND_DEGRADED
                status = STATUS_DEGRADED
                reward = (pool_share_wei * 25) // 100
                slash = 0
            else:
                band = BAND_OFFLINE_SLASH
                status = STATUS_SLASHED
                reward = 0
                # Slash 20 percent of bond, capped by existing bond
                slash = min(bond_wei, (bond_wei * 20) // 100)

        return (band, status, reward, slash)

    # -------------------------------------------------------------------------
    # Public views
    # -------------------------------------------------------------------------
    @gl.public.view
    def get_contract_accounting(self) -> dict:
        custody = int(self.native_custody_balance)
        bonds = int(self.active_node_bonds)
        pool = int(self.sponsor_reward_pool)
        refundable = int(self.total_refundable_balances)
        balanced = (custody == (bonds + pool + refundable))
        return {
            "native_custody_balance": custody,
            "active_node_bonds": bonds,
            "sponsor_reward_pool": pool,
            "total_refundable_balances": refundable,
            "invariant_holds": balanced,
            "residue_wei": custody - (bonds + pool + refundable),
        }

    @gl.public.view
    def get_node(self, node_id: str) -> dict:
        if node_id not in self.nodes:
            return {"exists": False}
        n = self.nodes[node_id]
        return {
            "exists": True,
            "operator": n.operator.as_hex,
            "hardware_id": n.hardware_id,
            "region_code": n.region_code,
            "target_uptime_bps": int(n.target_uptime_bps),
            "telemetry_endpoint_url": n.telemetry_endpoint_url,
            "staked_bond_wei": int(n.staked_bond_wei),
            "registered_at_ts": int(n.registered_at_ts),
            "status": n.status,
            "last_verified_epoch": int(n.last_verified_epoch),
            "lifetime_rewards_wei": int(n.lifetime_rewards_wei),
            "lifetime_slashed_wei": int(n.lifetime_slashed_wei),
        }

    @gl.public.view
    def get_epoch(self, epoch_id: u256) -> dict:
        if epoch_id not in self.epochs:
            return {"exists": False}
        ep = self.epochs[epoch_id]
        return {
            "exists": True,
            "epoch_id": int(ep.epoch_id),
            "sponsor": ep.sponsor.as_hex,
            "reward_pool_wei": int(ep.reward_pool_wei),
            "initial_pool_wei": int(ep.initial_pool_wei),
            "start_time_ts": int(ep.start_time_ts),
            "end_time_ts": int(ep.end_time_ts),
            "settled": ep.settled,
            "settled_node_count": int(ep.settled_node_count),
        }

    @gl.public.view
    def get_verification_record(self, record_key: str) -> dict:
        if record_key not in self.verification_records:
            return {"exists": False}
        vr = self.verification_records[record_key]
        return {
            "exists": True,
            "node_id": vr.node_id,
            "epoch_id": int(vr.epoch_id),
            "observed_uptime_bps": int(vr.observed_uptime_bps),
            "coverage_band": vr.coverage_band,
            "telemetry_verified": vr.telemetry_verified,
            "reward_awarded_wei": int(vr.reward_awarded_wei),
            "slash_applied_wei": int(vr.slash_applied_wei),
            "settled_at_ts": int(vr.settled_at_ts),
        }

    @gl.public.view
    def get_refundable_balance(self, account: Address) -> u256:
        if not isinstance(account, Address):
            account = Address(account)
        if account not in self.refundable_balances:
            return u256(0)
        return self.refundable_balances[account]

    # -------------------------------------------------------------------------
    # Public write methods (Payable & State Transitions)
    # -------------------------------------------------------------------------
    @gl.public.write.payable
    def fund_epoch_reward_pool_payable(
        self,
        epoch_id: u256,
        duration_seconds: u256,
    ) -> dict:
        """
        Fund epoch reward pool with native GEN.
        Non-trapping soft-fail: credits 100 percent of value to refundable_balances on error.
        """
        sender = gl.message.sender_address
        sent_value = gl.message.value
        self.native_custody_balance += sent_value

        # Soft-fail validation checks
        if sent_value == 0:
            return {"success": False, "reason": "Zero funding value", "refunded_wei": 0}

        if epoch_id in self.epochs:
            # Epoch already registered: soft refund
            self._credit_refundable(sender, sent_value)
            return {
                "success": False,
                "reason": "Epoch already exists",
                "refunded_wei": int(sent_value),
            }

        dur = int(duration_seconds)
        if dur < MIN_EPOCH_DURATION or dur > MAX_EPOCH_DURATION:
            self._credit_refundable(sender, sent_value)
            return {
                "success": False,
                "reason": "Epoch duration outside bounds",
                "refunded_wei": int(sent_value),
            }

        now_ts = self._get_consensus_time()
        start_ts = now_ts
        end_ts = now_ts + dur

        self.epochs[epoch_id] = EpochRewardPool(
            epoch_id=epoch_id,
            sponsor=sender,
            reward_pool_wei=sent_value,
            initial_pool_wei=sent_value,
            start_time_ts=u256(start_ts),
            end_time_ts=u256(end_ts),
            settled=False,
            settled_node_count=u256(0),
        )
        self.epoch_ids.append(epoch_id)
        self.sponsor_reward_pool += sent_value

        return {
            "success": True,
            "epoch_id": int(epoch_id),
            "funded_wei": int(sent_value),
            "start_time_ts": start_ts,
            "end_time_ts": end_ts,
        }

    @gl.public.write.payable
    def register_depin_node_payable(
        self,
        node_id: str,
        hardware_id: str,
        region_code: str,
        target_uptime_bps: u256,
        telemetry_endpoint_url: str,
    ) -> dict:
        """
        Register hardware node staking native GEN bond.
        Non-trapping soft-fail: credits 100 percent of value + surplus to refundable_balances.
        """
        sender = gl.message.sender_address
        sent_value = gl.message.value
        self.native_custody_balance += sent_value

        # Validate node_id non-empty and unique
        if not node_id or len(node_id) > 64:
            self._credit_refundable(sender, sent_value)
            return {"success": False, "reason": "Invalid node_id", "refunded_wei": int(sent_value)}

        if node_id in self.nodes:
            self._credit_refundable(sender, sent_value)
            return {"success": False, "reason": "Node ID already registered", "refunded_wei": int(sent_value)}

        # Validate hardware_id, region_code, url
        if not hardware_id or len(hardware_id) > 64 or not region_code or len(region_code) > 16:
            self._credit_refundable(sender, sent_value)
            return {"success": False, "reason": "Invalid hardware_id or region_code", "refunded_wei": int(sent_value)}

        if not telemetry_endpoint_url.startswith("https://"):
            self._credit_refundable(sender, sent_value)
            return {"success": False, "reason": "URL must start with https://", "refunded_wei": int(sent_value)}

        # Validate target_uptime_bps discrete 250-bps grid
        tgt_bps = int(target_uptime_bps)
        if tgt_bps < MIN_TARGET_BPS or tgt_bps > MAX_TARGET_BPS or (tgt_bps % GRID_STEP_BPS != 0):
            self._credit_refundable(sender, sent_value)
            return {"success": False, "reason": "target_uptime_bps must be multiple of 250 in [250, 10000]", "refunded_wei": int(sent_value)}

        # Check bond requirement
        if sent_value < self.min_node_bond_wei:
            self._credit_refundable(sender, sent_value)
            return {"success": False, "reason": "Insufficient bond amount", "refunded_wei": int(sent_value)}

        # Split bond and surplus
        bond_amount = self.min_node_bond_wei
        surplus = sent_value - bond_amount

        self.active_node_bonds += bond_amount
        if surplus > 0:
            self._credit_refundable(sender, surplus)

        now_ts = self._get_consensus_time()
        self.nodes[node_id] = DePINNode(
            operator=sender,
            hardware_id=hardware_id,
            region_code=region_code,
            target_uptime_bps=target_uptime_bps,
            telemetry_endpoint_url=telemetry_endpoint_url,
            staked_bond_wei=bond_amount,
            registered_at_ts=u256(now_ts),
            status=STATUS_ACTIVE,
            last_verified_epoch=u256(0),
            lifetime_rewards_wei=u256(0),
            lifetime_slashed_wei=u256(0),
        )
        self.node_ids.append(node_id)

        return {
            "success": True,
            "node_id": node_id,
            "staked_bond_wei": int(bond_amount),
            "surplus_refunded_wei": int(surplus),
        }

    @gl.public.write
    def verify_node_telemetry_epoch(self, node_id: str, epoch_id: u256) -> dict:
        """
        Verify telemetry after epoch close via nondet fetch and discrete 250-bps consensus.
        Enforces 100 percent exact validator agreement on prompt comparative.
        """
        if node_id not in self.nodes:
            raise gl.vm.UserError("Node not found")
        if epoch_id not in self.epochs:
            raise gl.vm.UserError("Epoch not found")

        node = self.nodes[node_id]
        epoch = self.epochs[epoch_id]

        now_ts = self._get_consensus_time()
        if now_ts < int(epoch.end_time_ts):
            raise gl.vm.UserError("Epoch window still active")

        record_key = f"{node_id}:{int(epoch_id)}"
        if record_key in self.verification_records:
            raise gl.vm.UserError("Node already verified for this epoch")

        # Snapshot storage into plain locals (Rule 4)
        target_bps_local = int(node.target_uptime_bps)
        bond_local = int(node.staked_bond_wei)
        node_hw_local = str(node.hardware_id)
        node_reg_local = str(node.region_code)
        url_local = str(node.telemetry_endpoint_url)
        avail_pool_local = int(epoch.reward_pool_wei)

        # Baseline per-node share allocation (max 50 percent of pool or remaining pool)
        base_share_wei = min(avail_pool_local, max(1, avail_pool_local // 2))

        def nondet_eval() -> dict:
            # Strictly fail closed on render failure or < 32 chars (Rule 9)
            raw_rendered = None
            try:
                raw_rendered = gl.nondet.web.render(url_local)
            except Exception:
                raw_rendered = None

            if not raw_rendered or len(raw_rendered) < 32:
                band, st, rew, slsh = self._compute_node_state(
                    observed_bps=0,
                    target_bps=target_bps_local,
                    telemetry_verified=False,
                    bond_wei=bond_local,
                    pool_share_wei=base_share_wei,
                )
                return {
                    "telemetry_verified": False,
                    "observed_uptime_bps": 0,
                    "coverage_band": band,
                    "reward_wei": rew,
                    "slash_wei": slsh,
                }

            # Defensively parse telemetry JSON
            try:
                first_brace = raw_rendered.find("{")
                last_brace = raw_rendered.rfind("}")
                if first_brace == -1 or last_brace == -1:
                    band, st, rew, slsh = self._compute_node_state(
                        observed_bps=0,
                        target_bps=target_bps_local,
                        telemetry_verified=False,
                        bond_wei=bond_local,
                        pool_share_wei=base_share_wei,
                    )
                    return {
                        "telemetry_verified": False,
                        "observed_uptime_bps": 0,
                        "coverage_band": band,
                        "reward_wei": rew,
                        "slash_wei": slsh,
                    }
                parsed = json.loads(raw_rendered[first_brace : last_brace + 1])
                parsed_hw = str(parsed.get("node_hardware_id", ""))
                parsed_reg = str(parsed.get("region_code", ""))
                raw_uptime = int(parsed.get("uptime_bps", 0))

                # Identity mismatch -> spoof detected -> slash
                if parsed_hw != node_hw_local or parsed_reg != node_reg_local:
                    band, st, rew, slsh = self._compute_node_state(
                        observed_bps=0,
                        target_bps=target_bps_local,
                        telemetry_verified=True,
                        bond_wei=bond_local,
                        pool_share_wei=base_share_wei,
                    )
                    return {
                        "telemetry_verified": True,
                        "observed_uptime_bps": 0,
                        "coverage_band": BAND_OFFLINE_SLASH,
                        "reward_wei": 0,
                        "slash_wei": min(bond_local, (bond_local * 20) // 100),
                    }

                # Discrete 250-bps grid quantization
                quantized_bps = self._quantize_uptime_bps(raw_uptime)
                band, st, rew, slsh = self._compute_node_state(
                    observed_bps=quantized_bps,
                    target_bps=target_bps_local,
                    telemetry_verified=True,
                    bond_wei=bond_local,
                    pool_share_wei=base_share_wei,
                )
                return {
                    "telemetry_verified": True,
                    "observed_uptime_bps": quantized_bps,
                    "coverage_band": band,
                    "reward_wei": rew,
                    "slash_wei": slsh,
                }
            except Exception:
                # Malformed payload -> fail closed
                band, st, rew, slsh = self._compute_node_state(
                    observed_bps=0,
                    target_bps=target_bps_local,
                    telemetry_verified=False,
                    bond_wei=bond_local,
                    pool_share_wei=base_share_wei,
                )
                return {
                    "telemetry_verified": False,
                    "observed_uptime_bps": 0,
                    "coverage_band": band,
                    "reward_wei": rew,
                    "slash_wei": slsh,
                }

        verdict = gl.eq_principle.prompt_comparative(
            nondet_eval,
            "Validators must agree exactly on telemetry_verified, observed_uptime_bps quantized on 250-bps grid, coverage_band, reward_wei, and slash_wei.",
        )

        telemetry_verified = bool(verdict["telemetry_verified"])
        observed_uptime_bps = int(verdict["observed_uptime_bps"])
        coverage_band = str(verdict["coverage_band"])
        reward_wei = int(verdict["reward_wei"])
        slash_wei = int(verdict["slash_wei"])

        # Enforce zero-slash invariant strictly
        if observed_uptime_bps >= target_bps_local:
            slash_wei = 0

        # Execute fund accounting transitions
        actual_reward = 0
        if reward_wei > 0:
            actual_reward = min(reward_wei, int(epoch.reward_pool_wei))
            epoch.reward_pool_wei -= u256(actual_reward)
            self.sponsor_reward_pool -= u256(actual_reward)
            self._credit_refundable(node.operator, u256(actual_reward))
            node.lifetime_rewards_wei += u256(actual_reward)

        actual_slash = 0
        if slash_wei > 0:
            actual_slash = min(slash_wei, int(node.staked_bond_wei))
            node.staked_bond_wei -= u256(actual_slash)
            self.active_node_bonds -= u256(actual_slash)
            # Slashed collateral returned to pool to preserve custody
            self.sponsor_reward_pool += u256(actual_slash)
            epoch.reward_pool_wei += u256(actual_slash)
            node.lifetime_slashed_wei += u256(actual_slash)

        # Update node status
        node.last_verified_epoch = epoch_id
        if coverage_band in (BAND_OPTIMAL, BAND_STANDARD):
            node.status = STATUS_VERIFIED
        elif coverage_band == BAND_DEGRADED:
            node.status = STATUS_DEGRADED
        elif coverage_band == BAND_OFFLINE_SLASH:
            node.status = STATUS_SLASHED
        else:
            node.status = STATUS_UNVERIFIED

        epoch.settled_node_count += u256(1)

        self.verification_records[record_key] = EpochVerificationRecord(
            node_id=node_id,
            epoch_id=epoch_id,
            observed_uptime_bps=u256(observed_uptime_bps),
            coverage_band=coverage_band,
            telemetry_verified=telemetry_verified,
            reward_awarded_wei=u256(actual_reward),
            slash_applied_wei=u256(actual_slash),
            settled_at_ts=u256(now_ts),
        )

        return {
            "node_id": node_id,
            "epoch_id": int(epoch_id),
            "telemetry_verified": telemetry_verified,
            "observed_uptime_bps": observed_uptime_bps,
            "coverage_band": coverage_band,
            "reward_awarded_wei": actual_reward,
            "slash_applied_wei": actual_slash,
        }

    @gl.public.write
    def claim_expired_epoch_refund(self, epoch_id: u256) -> dict:
        """
        Refund 100 percent of remaining reward pool to sponsor on epoch timeout (Rule 10).
        """
        if epoch_id not in self.epochs:
            raise gl.vm.UserError("Epoch not found")

        epoch = self.epochs[epoch_id]
        sender = gl.message.sender_address

        if sender != epoch.sponsor:
            raise gl.vm.UserError("Only epoch sponsor can claim refund")

        now_ts = self._get_consensus_time()
        if now_ts < int(epoch.end_time_ts):
            raise gl.vm.UserError("Epoch has not expired yet")

        remaining = int(epoch.reward_pool_wei)
        if remaining == 0:
            return {"success": False, "reason": "Reward pool empty", "refunded_wei": 0}

        epoch.reward_pool_wei = u256(0)
        epoch.settled = True
        self.sponsor_reward_pool -= u256(remaining)
        self._credit_refundable(sender, u256(remaining))

        return {
            "success": True,
            "epoch_id": int(epoch_id),
            "refunded_wei": remaining,
        }

    @gl.public.write
    def withdraw_refundable_balance(self) -> dict:
        """
        Withdraw credited refundable balance via IEoaRecipient.emit_transfer.
        Preserves balance intact if delivery fails (Rule 3 & 8).
        """
        sender = gl.message.sender_address
        if sender not in self.refundable_balances:
            return {"success": False, "reason": "No refundable balance", "amount": 0}

        amount = self.refundable_balances[sender]
        if amount == 0:
            return {"success": False, "reason": "Zero balance", "amount": 0}

        # Checks-Effects: deduct state first
        self.refundable_balances[sender] = u256(0)
        self.total_refundable_balances -= amount
        self.native_custody_balance -= amount

        try:
            recipient = IEoaRecipient(sender)
            recipient.emit_transfer(value=amount)
        except Exception:
            # Revert state changes if transfer fails
            self.refundable_balances[sender] = amount
            self.total_refundable_balances += amount
            self.native_custody_balance += amount
            return {"success": False, "reason": "Transfer failed", "amount": 0}

        return {
            "success": True,
            "recipient": sender.as_hex,
            "amount": int(amount),
        }
