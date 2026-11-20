import os
import sys
import glob
import tempfile
import atexit

# Ensure cached genlayer stdlib is in sys.path
cache_roots = glob.glob(os.path.expanduser("~/.cache/gltest-direct/extracted/*/py-lib-genlayer-std/*"))
for r in cache_roots:
    if r not in sys.path:
        sys.path.insert(0, r)

import gltest.direct.loader as loader
import gltest.direct.vm as vmm

_temp_files = []

def _cleanup_temp_files():
    for p in _temp_files:
        try:
            if os.path.exists(p):
                os.unlink(p)
        except Exception:
            pass

atexit.register(_cleanup_temp_files)

def _patched_inject_message_to_fd0(vm):
    try:
        from genlayer.py import calldata
        from genlayer.py.types import Address
    except ImportError:
        return

    sender_addr = vm.sender
    if isinstance(sender_addr, bytes):
        sender_addr = Address(sender_addr)

    contract_addr = vm._contract_address
    if isinstance(contract_addr, bytes):
        contract_addr = Address(contract_addr)

    origin_addr = vm.origin
    if isinstance(origin_addr, bytes):
        origin_addr = Address(origin_addr)

    message_data = {
        'contract_address': contract_addr,
        'sender_address': sender_addr,
        'origin_address': origin_addr,
        'stack': [],
        'value': vm._value,
        'datetime': vm._datetime,
        'is_init': False,
        'chain_id': vm._chain_id,
        'entry_kind': 0,
        'entry_data': b'',
        'entry_stage_data': None,
    }

    encoded = calldata.encode(message_data)

    fd, path = tempfile.mkstemp()
    _temp_files.append(path)
    try:
        os.write(fd, encoded)
        os.lseek(fd, 0, os.SEEK_SET)

        original_stdin = os.dup(0)
        vm._original_stdin_fd = original_stdin

        os.dup2(fd, 0)
    finally:
        os.close(fd)
        try:
            os.unlink(path)
        except PermissionError:
            pass

loader._inject_message_to_fd0 = _patched_inject_message_to_fd0

_orig_refresh = vmm.VMContext._refresh_gl_message

def _patched_refresh_gl_message(self):
    _orig_refresh(self)
    if 'genlayer.gl' in sys.modules:
        gl = sys.modules['genlayer.gl']
        if hasattr(gl, 'message_raw') and gl.message_raw is not None:
            gl.message_raw['datetime'] = self._datetime

vmm.VMContext._refresh_gl_message = _patched_refresh_gl_message

import pytest

@pytest.fixture(autouse=True)
def _set_deterministic_baseline_clock(direct_vm):
    direct_vm.warp("2026-11-20T10:00:00Z")

