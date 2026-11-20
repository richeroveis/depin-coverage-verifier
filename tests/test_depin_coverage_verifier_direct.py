import json
import pytest

CONTRACT_PATH = "contracts/depin_coverage_verifier.py"

MIN_BOND = 1000
EPOCH_DURATION = 3600  # 1 hour

def test_init_success(direct_vm, direct_deploy, direct_alice):
    direct_vm.sender = direct_alice
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    acct = contract.get_contract_accounting()
    assert acct["native_custody_balance"] == 0
    assert acct["active_node_bonds"] == 0
    assert acct["sponsor_reward_pool"] == 0
    assert acct["total_refundable_balances"] == 0
    assert acct["invariant_holds"] is True
    assert acct["residue_wei"] == 0

def test_init_zero_bond_reverts(direct_vm, direct_deploy, direct_alice):
    direct_vm.sender = direct_alice
    with pytest.raises(Exception):
        direct_deploy(CONTRACT_PATH, 0)

def test_init_accounting_view(direct_vm, direct_deploy, direct_alice):
    direct_vm.sender = direct_alice
    contract = direct_deploy(CONTRACT_PATH, 500)
    acct = contract.get_contract_accounting()
    assert acct["invariant_holds"] is True
    assert acct["residue_wei"] == 0

def test_init_empty_queries(direct_vm, direct_deploy, direct_alice):
    direct_vm.sender = direct_alice
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    assert contract.get_node("nonexistent")["exists"] is False
    assert contract.get_epoch(999)["exists"] is False
    assert contract.get_verification_record("none:1")["exists"] is False
    assert contract.get_refundable_balance(direct_alice) == 0

def test_fund_epoch_success(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 5000
    res = contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)
    assert res["success"] is True
    assert res["funded_wei"] == 5000
    ep = contract.get_epoch(1)
    assert ep["exists"] is True
    assert ep["reward_pool_wei"] == 5000
    expected_addr = ("0x" + direct_bob.hex()).lower() if isinstance(direct_bob, bytes) else str(direct_bob).lower()
    assert ep["sponsor"].lower() == expected_addr
    acct = contract.get_contract_accounting()
    assert acct["sponsor_reward_pool"] == 5000
    assert acct["native_custody_balance"] == 5000
    assert acct["invariant_holds"] is True

def test_fund_epoch_zero_value_soft_fail(direct_vm, direct_deploy, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 0
    res = contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)
    assert res["success"] is False
    assert res["reason"] == "Zero funding value"
    acct = contract.get_contract_accounting()
    assert acct["invariant_holds"] is True

def test_fund_epoch_duplicate_soft_fail(direct_vm, direct_deploy, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 5000
    res1 = contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)
    assert res1["success"] is True

    # Duplicate funding of same epoch id
    direct_vm.value = 3000
    res2 = contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)
    assert res2["success"] is False
    assert res2["reason"] == "Epoch already exists"
    assert res2["refunded_wei"] == 3000
    assert contract.get_refundable_balance(direct_bob) == 3000
    acct = contract.get_contract_accounting()
    assert acct["native_custody_balance"] == 8000
    assert acct["sponsor_reward_pool"] == 5000
    assert acct["total_refundable_balances"] == 3000
    assert acct["invariant_holds"] is True

def test_fund_epoch_duration_below_floor_soft_fail(direct_vm, direct_deploy, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 2000
    res = contract.fund_epoch_reward_pool_payable(1, 30)  # 30s < 60s floor
    assert res["success"] is False
    assert res["reason"] == "Epoch duration outside bounds"
    assert contract.get_refundable_balance(direct_bob) == 2000
    acct = contract.get_contract_accounting()
    assert acct["invariant_holds"] is True

def test_fund_epoch_duration_above_ceiling_soft_fail(direct_vm, direct_deploy, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 2000
    res = contract.fund_epoch_reward_pool_payable(1, 3000000)  # > 30 days
    assert res["success"] is False
    assert res["reason"] == "Epoch duration outside bounds"
    assert contract.get_refundable_balance(direct_bob) == 2000
    acct = contract.get_contract_accounting()
    assert acct["invariant_holds"] is True

def test_fund_multiple_epochs_accounting(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_alice
    direct_vm.value = 4000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_bob
    direct_vm.value = 6000
    contract.fund_epoch_reward_pool_payable(2, EPOCH_DURATION)

    acct = contract.get_contract_accounting()
    assert acct["sponsor_reward_pool"] == 10000
    assert acct["native_custody_balance"] == 10000
    assert acct["invariant_holds"] is True

def test_fund_epoch_preserves_custody_invariant(direct_vm, direct_deploy, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)
    acct = contract.get_contract_accounting()
    assert acct["invariant_holds"] is True
    assert acct["residue_wei"] == 0

def test_register_node_success(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    res = contract.register_depin_node_payable(
        "node-001",
        "HW-001",
        "US-WEST",
        9500,
        "https://telemetry.depin.io/node-001",
    )
    assert res["success"] is True
    assert res["staked_bond_wei"] == MIN_BOND
    node = contract.get_node("node-001")
    assert node["exists"] is True
    assert node["status"] == "ACTIVE"
    assert node["staked_bond_wei"] == MIN_BOND
    acct = contract.get_contract_accounting()
    assert acct["active_node_bonds"] == MIN_BOND
    assert acct["native_custody_balance"] == MIN_BOND
    assert acct["invariant_holds"] is True

def test_register_node_surplus_refund(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_alice
    direct_vm.value = 1500  # 500 surplus
    res = contract.register_depin_node_payable(
        "node-002",
        "HW-002",
        "US-EAST",
        9750,
        "https://telemetry.depin.io/node-002",
    )
    assert res["success"] is True
    assert res["staked_bond_wei"] == MIN_BOND
    assert res["surplus_refunded_wei"] == 500
    assert contract.get_refundable_balance(direct_alice) == 500
    acct = contract.get_contract_accounting()
    assert acct["active_node_bonds"] == MIN_BOND
    assert acct["total_refundable_balances"] == 500
    assert acct["native_custody_balance"] == 1500
    assert acct["invariant_holds"] is True

def test_register_node_insufficient_bond_soft_fail(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_alice
    direct_vm.value = 500  # < MIN_BOND
    res = contract.register_depin_node_payable(
        "node-003",
        "HW-003",
        "EU-CENTRAL",
        9500,
        "https://telemetry.depin.io/node-003",
    )
    assert res["success"] is False
    assert res["reason"] == "Insufficient bond amount"
    assert contract.get_refundable_balance(direct_alice) == 500
    acct = contract.get_contract_accounting()
    assert acct["active_node_bonds"] == 0
    assert acct["total_refundable_balances"] == 500
    assert acct["invariant_holds"] is True

def test_register_node_duplicate_id_soft_fail(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-001", "HW-001", "US-WEST", 9500, "https://telemetry.depin.io/node-001")

    direct_vm.value = MIN_BOND
    res2 = contract.register_depin_node_payable("node-001", "HW-001-ALT", "US-WEST", 9500, "https://telemetry.depin.io/node-001")
    assert res2["success"] is False
    assert res2["reason"] == "Node ID already registered"
    assert contract.get_refundable_balance(direct_alice) == MIN_BOND
    acct = contract.get_contract_accounting()
    assert acct["invariant_holds"] is True

def test_register_node_empty_id_soft_fail(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    res = contract.register_depin_node_payable("", "HW-001", "US-WEST", 9500, "https://telemetry.depin.io/node-001")
    assert res["success"] is False
    assert contract.get_refundable_balance(direct_alice) == MIN_BOND

def test_register_node_long_id_soft_fail(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    long_id = "n" * 65
    res = contract.register_depin_node_payable(long_id, "HW-001", "US-WEST", 9500, "https://telemetry.depin.io/node-001")
    assert res["success"] is False
    assert contract.get_refundable_balance(direct_alice) == MIN_BOND

def test_register_node_invalid_url_protocol_soft_fail(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    res = contract.register_depin_node_payable("node-http", "HW-HTTP", "US-WEST", 9500, "http://insecure.depin.io")
    assert res["success"] is False
    assert res["reason"] == "URL must start with https://"
    assert contract.get_refundable_balance(direct_alice) == MIN_BOND

def test_register_node_invalid_target_bps_bounds(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    res1 = contract.register_depin_node_payable("node-0", "HW-0", "US", 0, "https://telemetry.depin.io/node-0")
    assert res1["success"] is False

    direct_vm.value = MIN_BOND
    res2 = contract.register_depin_node_payable("node-10025", "HW-10025", "US", 10250, "https://telemetry.depin.io/node-10025")
    assert res2["success"] is False

def test_register_node_non_grid_target_bps_soft_fail(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    res = contract.register_depin_node_payable("node-9820", "HW-9820", "US", 9820, "https://telemetry.depin.io/node-9820")
    assert res["success"] is False
    assert "multiple of 250" in res["reason"]

def test_telemetry_fetch_failure_fail_closed(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    # Sponsor funds epoch
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    # Node registers
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-fail", "HW-FAIL", "US", 9500, "https://telemetry.depin.io/fail")

    # Warp past epoch end
    direct_vm.warp("2026-11-20T14:00:00Z")

    # Mock web failure / 500 error
    direct_vm.mock_web(r".*telemetry\.depin\.io/fail.*", {"status": 500, "body": "Internal Server Error"})

    res = contract.verify_node_telemetry_epoch("node-fail", 1)
    assert res["telemetry_verified"] is False
    assert res["coverage_band"] == "TELEMETRY_UNAVAILABLE_FAIL_CLOSED"
    assert res["reward_awarded_wei"] == 0
    assert res["slash_applied_wei"] == 0

    node = contract.get_node("node-fail")
    assert node["staked_bond_wei"] == MIN_BOND
    assert node["status"] == "UNVERIFIED"

def test_telemetry_short_payload_fail_closed(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-short", "HW-SHORT", "US", 9500, "https://telemetry.depin.io/short")

    direct_vm.warp("2026-11-20T14:00:00Z")
    # Payload < 32 chars
    direct_vm.mock_web(r".*telemetry\.depin\.io/short.*", {"status": 200, "body": '{"ok":true}'})

    res = contract.verify_node_telemetry_epoch("node-short", 1)
    assert res["telemetry_verified"] is False
    assert res["coverage_band"] == "TELEMETRY_UNAVAILABLE_FAIL_CLOSED"
    assert res["reward_awarded_wei"] == 0
    assert res["slash_applied_wei"] == 0

def test_telemetry_malformed_json_fail_closed(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-mal", "HW-MAL", "US", 9500, "https://telemetry.depin.io/mal")

    direct_vm.warp("2026-11-20T14:00:00Z")
    direct_vm.mock_web(r".*telemetry\.depin\.io/mal.*", {"status": 200, "body": "This is non JSON data but long enough to be over 32 chars"})

    res = contract.verify_node_telemetry_epoch("node-mal", 1)
    assert res["telemetry_verified"] is False
    assert res["coverage_band"] == "TELEMETRY_UNAVAILABLE_FAIL_CLOSED"

def test_telemetry_empty_body_fail_closed(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-empty", "HW-EMPTY", "US", 9500, "https://telemetry.depin.io/empty")

    direct_vm.warp("2026-11-20T14:00:00Z")
    direct_vm.mock_web(r".*telemetry\.depin\.io/empty.*", {"status": 200, "body": ""})

    res = contract.verify_node_telemetry_epoch("node-empty", 1)
    assert res["telemetry_verified"] is False
    assert res["coverage_band"] == "TELEMETRY_UNAVAILABLE_FAIL_CLOSED"

def test_telemetry_html_error_page_fail_closed(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-html", "HW-HTML", "US", 9500, "https://telemetry.depin.io/html")

    direct_vm.warp("2026-11-20T14:00:00Z")
    html_page = "<html><body><h1>502 Bad Gateway</h1><p>Cloudflare reverse proxy timeout</p></body></html>"
    direct_vm.mock_web(r".*telemetry\.depin\.io/html.*", {"status": 502, "body": html_page})

    res = contract.verify_node_telemetry_epoch("node-html", 1)
    assert res["telemetry_verified"] is False
    assert res["coverage_band"] == "TELEMETRY_UNAVAILABLE_FAIL_CLOSED"

def test_telemetry_fail_closed_preserves_bond(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-pres", "HW-PRES", "US", 9500, "https://telemetry.depin.io/pres")

    direct_vm.warp("2026-11-20T14:00:00Z")
    direct_vm.mock_web(r".*telemetry\.depin\.io/pres.*", {"status": 504, "body": "Gateway Timeout"})

    contract.verify_node_telemetry_epoch("node-pres", 1)
    node = contract.get_node("node-pres")
    assert node["staked_bond_wei"] == MIN_BOND
    assert node["lifetime_slashed_wei"] == 0
    acct = contract.get_contract_accounting()
    assert acct["active_node_bonds"] == MIN_BOND
    assert acct["invariant_holds"] is True

def test_coverage_optimal_relay_bonus(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-opt", "HW-OPT", "US", 9500, "https://telemetry.depin.io/opt")

    direct_vm.warp("2026-11-20T14:00:00Z")
    telemetry = json.dumps({
        "node_hardware_id": "HW-OPT",
        "region_code": "US",
        "uptime_bps": 9850,
        "heartbeats": 1440,
    })
    direct_vm.mock_web(r".*telemetry\.depin\.io/opt.*", {"status": 200, "body": telemetry})

    res = contract.verify_node_telemetry_epoch("node-opt", 1)
    assert res["telemetry_verified"] is True
    assert res["observed_uptime_bps"] == 9750  # 9850 quantized on 250 grid
    assert res["coverage_band"] == "OPTIMAL_RELAY_BONUS"
    assert res["reward_awarded_wei"] == 5000  # full 50% pool share
    assert res["slash_applied_wei"] == 0
    assert contract.get_refundable_balance(direct_alice) == 5000
    acct = contract.get_contract_accounting()
    assert acct["invariant_holds"] is True

def test_coverage_standard_uptime_pass(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-std", "HW-STD", "US", 9000, "https://telemetry.depin.io/std")

    direct_vm.warp("2026-11-20T14:00:00Z")
    telemetry = json.dumps({
        "node_hardware_id": "HW-STD",
        "region_code": "US",
        "uptime_bps": 9200,
        "heartbeats": 1350,
    })
    direct_vm.mock_web(r".*telemetry\.depin\.io/std.*", {"status": 200, "body": telemetry})

    res = contract.verify_node_telemetry_epoch("node-std", 1)
    assert res["telemetry_verified"] is True
    assert res["observed_uptime_bps"] == 9000
    assert res["coverage_band"] == "STANDARD_UPTIME_PASS"
    assert res["reward_awarded_wei"] == 4000  # 80% of 5000 share
    assert res["slash_applied_wei"] == 0
    acct = contract.get_contract_accounting()
    assert acct["invariant_holds"] is True

def test_coverage_degraded_throttle_penalty(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-deg", "HW-DEG", "US", 9000, "https://telemetry.depin.io/deg")

    direct_vm.warp("2026-11-20T14:00:00Z")
    telemetry = json.dumps({
        "node_hardware_id": "HW-DEG",
        "region_code": "US",
        "uptime_bps": 6000,
        "heartbeats": 900,
    })
    direct_vm.mock_web(r".*telemetry\.depin\.io/deg.*", {"status": 200, "body": telemetry})

    res = contract.verify_node_telemetry_epoch("node-deg", 1)
    assert res["telemetry_verified"] is True
    assert res["observed_uptime_bps"] == 6000
    assert res["coverage_band"] == "DEGRADED_THROTTLE_PENALTY"
    assert res["reward_awarded_wei"] == 1250  # 25% of 5000 share
    assert res["slash_applied_wei"] == 0
    acct = contract.get_contract_accounting()
    assert acct["invariant_holds"] is True

def test_coverage_offline_spoof_slash(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-slash", "HW-SLASH", "US", 9000, "https://telemetry.depin.io/slash")

    direct_vm.warp("2026-11-20T14:00:00Z")
    telemetry = json.dumps({
        "node_hardware_id": "HW-SLASH",
        "region_code": "US",
        "uptime_bps": 2000,  # < half of 9000
        "heartbeats": 300,
    })
    direct_vm.mock_web(r".*telemetry\.depin\.io/slash.*", {"status": 200, "body": telemetry})

    res = contract.verify_node_telemetry_epoch("node-slash", 1)
    assert res["telemetry_verified"] is True
    assert res["observed_uptime_bps"] == 2000
    assert res["coverage_band"] == "OFFLINE_SPOOF_SLASH"
    assert res["reward_awarded_wei"] == 0
    assert res["slash_applied_wei"] == 200  # 20% of 1000 bond

    node = contract.get_node("node-slash")
    assert node["staked_bond_wei"] == 800
    assert node["lifetime_slashed_wei"] == 200
    acct = contract.get_contract_accounting()
    assert acct["active_node_bonds"] == 800
    assert acct["invariant_holds"] is True

def test_hardware_id_mismatch_spoof_slashed(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-spoof-hw", "HW-REAL", "US", 9000, "https://telemetry.depin.io/spoof-hw")

    direct_vm.warp("2026-11-20T14:00:00Z")
    # Different hardware id returned by endpoint
    telemetry = json.dumps({
        "node_hardware_id": "HW-ATTACKER-FAKE",
        "region_code": "US",
        "uptime_bps": 10000,
    })
    direct_vm.mock_web(r".*telemetry\.depin\.io/spoof-hw.*", {"status": 200, "body": telemetry})

    res = contract.verify_node_telemetry_epoch("node-spoof-hw", 1)
    assert res["coverage_band"] == "OFFLINE_SPOOF_SLASH"
    assert res["reward_awarded_wei"] == 0
    assert res["slash_applied_wei"] == 200
    node = contract.get_node("node-spoof-hw")
    assert node["status"] == "SLASHED"

def test_region_code_mismatch_spoof_slashed(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-spoof-reg", "HW-REG", "US-WEST", 9000, "https://telemetry.depin.io/spoof-reg")

    direct_vm.warp("2026-11-20T14:00:00Z")
    # Different region code returned
    telemetry = json.dumps({
        "node_hardware_id": "HW-REG",
        "region_code": "RU-SPOOF",
        "uptime_bps": 10000,
    })
    direct_vm.mock_web(r".*telemetry\.depin\.io/spoof-reg.*", {"status": 200, "body": telemetry})

    res = contract.verify_node_telemetry_epoch("node-spoof-reg", 1)
    assert res["coverage_band"] == "OFFLINE_SPOOF_SLASH"
    assert res["reward_awarded_wei"] == 0
    assert res["slash_applied_wei"] == 200

def test_quantization_discrete_increments(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    assert contract._quantize_uptime_bps(9999) == 9750
    assert contract._quantize_uptime_bps(9750) == 9750
    assert contract._quantize_uptime_bps(9749) == 9500
    assert contract._quantize_uptime_bps(250) == 250
    assert contract._quantize_uptime_bps(249) == 0
    assert contract._quantize_uptime_bps(0) == 0
    assert contract._quantize_uptime_bps(-10) == 0
    assert contract._quantize_uptime_bps(10000) == 10000

def test_zero_slash_when_observed_equals_target(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-eq", "HW-EQ", "US", 9000, "https://telemetry.depin.io/eq")

    direct_vm.warp("2026-11-20T14:00:00Z")
    telemetry = json.dumps({"node_hardware_id": "HW-EQ", "region_code": "US", "uptime_bps": 9000})
    direct_vm.mock_web(r".*telemetry\.depin\.io/eq.*", {"status": 200, "body": telemetry})

    res = contract.verify_node_telemetry_epoch("node-eq", 1)
    assert res["slash_applied_wei"] == 0
    assert res["observed_uptime_bps"] == 9000

def test_zero_slash_when_observed_exceeds_target(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-exc", "HW-EXC", "US", 8500, "https://telemetry.depin.io/exc")

    direct_vm.warp("2026-11-20T14:00:00Z")
    telemetry = json.dumps({"node_hardware_id": "HW-EXC", "region_code": "US", "uptime_bps": 9600})
    direct_vm.mock_web(r".*telemetry\.depin\.io/exc.*", {"status": 200, "body": telemetry})

    res = contract.verify_node_telemetry_epoch("node-exc", 1)
    assert res["slash_applied_wei"] == 0
    assert res["observed_uptime_bps"] == 9500

def test_zero_slash_at_minimum_grid_step(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-min", "HW-MIN", "US", 250, "https://telemetry.depin.io/min")

    direct_vm.warp("2026-11-20T14:00:00Z")
    telemetry = json.dumps({"node_hardware_id": "HW-MIN", "region_code": "US", "uptime_bps": 250})
    direct_vm.mock_web(r".*telemetry\.depin\.io/min.*", {"status": 200, "body": telemetry})

    res = contract.verify_node_telemetry_epoch("node-min", 1)
    assert res["slash_applied_wei"] == 0

def test_zero_slash_at_100_percent_uptime(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-100", "HW-100", "US", 10000, "https://telemetry.depin.io/100")

    direct_vm.warp("2026-11-20T14:00:00Z")
    telemetry = json.dumps({"node_hardware_id": "HW-100", "region_code": "US", "uptime_bps": 10000})
    direct_vm.mock_web(r".*telemetry\.depin\.io/100.*", {"status": 200, "body": telemetry})

    res = contract.verify_node_telemetry_epoch("node-100", 1)
    assert res["slash_applied_wei"] == 0
    assert res["coverage_band"] == "OPTIMAL_RELAY_BONUS"

def test_verify_nonexistent_node_reverts(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.warp("2026-11-20T14:00:00Z")
    with pytest.raises(Exception, match="Node not found"):
        contract.verify_node_telemetry_epoch("ghost-node", 1)

def test_verify_nonexistent_epoch_reverts(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-ok", "HW-OK", "US", 9500, "https://telemetry.depin.io/ok")

    with pytest.raises(Exception, match="Epoch not found"):
        contract.verify_node_telemetry_epoch("node-ok", 999)

def test_verify_epoch_window_active_reverts(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-act", "HW-ACT", "US", 9500, "https://telemetry.depin.io/act")

    # Time not warped past epoch end
    with pytest.raises(Exception, match="Epoch window still active"):
        contract.verify_node_telemetry_epoch("node-act", 1)

def test_verify_epoch_window_closed_succeeds(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-close", "HW-CLOSE", "US", 9500, "https://telemetry.depin.io/close")

    direct_vm.warp("2026-11-20T14:00:00Z")
    telemetry = json.dumps({"node_hardware_id": "HW-CLOSE", "region_code": "US", "uptime_bps": 9500})
    direct_vm.mock_web(r".*telemetry\.depin\.io/close.*", {"status": 200, "body": telemetry})

    res = contract.verify_node_telemetry_epoch("node-close", 1)
    assert res["observed_uptime_bps"] == 9500

def test_verify_node_already_verified_reverts(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-dup-ver", "HW-DUP", "US", 9500, "https://telemetry.depin.io/dup")

    direct_vm.warp("2026-11-20T14:00:00Z")
    telemetry = json.dumps({"node_hardware_id": "HW-DUP", "region_code": "US", "uptime_bps": 9500})
    direct_vm.mock_web(r".*telemetry\.depin\.io/dup.*", {"status": 200, "body": telemetry})

    contract.verify_node_telemetry_epoch("node-dup-ver", 1)
    with pytest.raises(Exception, match="already verified"):
        contract.verify_node_telemetry_epoch("node-dup-ver", 1)

def test_claim_expired_epoch_before_expiry_reverts(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    with pytest.raises(Exception, match="Epoch has not expired yet"):
        contract.claim_expired_epoch_refund(1)

def test_claim_expired_epoch_unauthorized_reverts(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.warp("2026-11-20T14:00:00Z")
    # Alice (not sponsor) tries to claim refund
    direct_vm.sender = direct_alice
    with pytest.raises(Exception, match="Only epoch sponsor"):
        contract.claim_expired_epoch_refund(1)

def test_claim_expired_epoch_100_percent_refund(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.warp("2026-11-20T14:00:00Z")
    # Sponsor Bob claims 100% refund
    direct_vm.sender = direct_bob
    res = contract.claim_expired_epoch_refund(1)
    assert res["success"] is True
    assert res["refunded_wei"] == 10000
    assert contract.get_refundable_balance(direct_bob) == 10000
    ep = contract.get_epoch(1)
    assert ep["settled"] is True
    assert ep["reward_pool_wei"] == 0
    acct = contract.get_contract_accounting()
    assert acct["sponsor_reward_pool"] == 0
    assert acct["total_refundable_balances"] == 10000
    assert acct["native_custody_balance"] == 10000
    assert acct["invariant_holds"] is True

def test_claim_expired_epoch_already_settled_empty(direct_vm, direct_deploy, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.warp("2026-11-20T14:00:00Z")
    contract.claim_expired_epoch_refund(1)

    # Second claim
    res2 = contract.claim_expired_epoch_refund(1)
    assert res2["success"] is False
    assert res2["reason"] == "Reward pool empty"

def test_withdraw_zero_balance_noop(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_alice
    res = contract.withdraw_refundable_balance()
    assert res["success"] is False
    assert res["reason"] == "No refundable balance" or res["reason"] == "Zero balance"

def test_withdraw_successful_eoa_delivery(direct_vm, direct_deploy, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 10000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)

    direct_vm.warp("2026-11-20T14:00:00Z")
    contract.claim_expired_epoch_refund(1)
    assert contract.get_refundable_balance(direct_bob) == 10000

    # Withdraw to EOA
    res = contract.withdraw_refundable_balance()
    assert res["success"] is True
    assert res["amount"] == 10000
    assert contract.get_refundable_balance(direct_bob) == 0
    acct = contract.get_contract_accounting()
    assert acct["native_custody_balance"] == 0
    assert acct["total_refundable_balances"] == 0
    assert acct["invariant_holds"] is True

def test_withdraw_partial_or_multiple_times(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_alice
    # Soft fail gives 500
    direct_vm.value = 500
    contract.register_depin_node_payable("n1", "HW1", "US", 9500, "https://test.io")
    assert contract.get_refundable_balance(direct_alice) == 500

    res1 = contract.withdraw_refundable_balance()
    assert res1["success"] is True
    assert res1["amount"] == 500
    assert contract.get_refundable_balance(direct_alice) == 0

    # Second withdrawal should be zero
    res2 = contract.withdraw_refundable_balance()
    assert res2["success"] is False

def test_accounting_invariant_all_flows(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    # 1. Sponsor funds pool
    direct_vm.sender = direct_bob
    direct_vm.value = 20000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)
    acct = contract.get_contract_accounting()
    assert acct["invariant_holds"] is True

    # 2. Alice stakes node with surplus
    direct_vm.sender = direct_alice
    direct_vm.value = 1500
    contract.register_depin_node_payable("node-all", "HW-ALL", "US", 9500, "https://telemetry.depin.io/all")
    acct = contract.get_contract_accounting()
    assert acct["invariant_holds"] is True

    # 3. Telemetry verified with optimal bonus
    direct_vm.warp("2026-11-20T14:00:00Z")
    telemetry = json.dumps({"node_hardware_id": "HW-ALL", "region_code": "US", "uptime_bps": 9850})
    direct_vm.mock_web(r".*telemetry\.depin\.io/all.*", {"status": 200, "body": telemetry})
    contract.verify_node_telemetry_epoch("node-all", 1)
    acct = contract.get_contract_accounting()
    assert acct["invariant_holds"] is True

    # 4. Alice withdraws her rewards + surplus
    direct_vm.sender = direct_alice
    contract.withdraw_refundable_balance()
    acct = contract.get_contract_accounting()
    assert acct["invariant_holds"] is True

    # 5. Bob claims remaining expired epoch funds
    direct_vm.sender = direct_bob
    contract.claim_expired_epoch_refund(1)
    acct = contract.get_contract_accounting()
    assert acct["invariant_holds"] is True

    # 6. Bob withdraws
    contract.withdraw_refundable_balance()
    acct = contract.get_contract_accounting()
    assert acct["invariant_holds"] is True

def test_zero_wei_stranded_residue(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT_PATH, MIN_BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = 5000
    contract.fund_epoch_reward_pool_payable(1, EPOCH_DURATION)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.register_depin_node_payable("node-res", "HW-RES", "US", 9000, "https://telemetry.depin.io/res")

    direct_vm.warp("2026-11-20T14:00:00Z")
    telemetry = json.dumps({"node_hardware_id": "HW-RES", "region_code": "US", "uptime_bps": 2000})
    direct_vm.mock_web(r".*telemetry\.depin\.io/res.*", {"status": 200, "body": telemetry})
    contract.verify_node_telemetry_epoch("node-res", 1)

    acct = contract.get_contract_accounting()
    assert acct["residue_wei"] == 0
    assert acct["invariant_holds"] is True
