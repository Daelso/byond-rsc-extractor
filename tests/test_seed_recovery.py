"""Regression tests for seed recovery behavior."""
from __future__ import annotations

import pathlib

import pytest

from extract_rsc import (
    ENCRYPTION_FLAG,
    RscEntry,
    build_seed_helper,
    byond_step_state,
    decrypt_beyond_payload,
    recover_encryption_seeds,
    seed_pattern_for_entry,
    u32,
)


PNG_SIG = b"\x89PNG\r\n\x1a\n"


def encrypt_beyond_payload(data: bytes, seed: int) -> bytes:
    state = u32(seed)
    out = bytearray(len(data))
    for i, plain_byte in enumerate(data):
        cipher_byte = plain_byte ^ (state & 0xFF)
        out[i] = cipher_byte
        state = byond_step_state(state, cipher_byte)
    return bytes(out)


def make_entry(index: int, name: str, base_type: int, seed: int, plain: bytes) -> RscEntry:
    return RscEntry(
        index=index,
        source="test",
        entry_type=base_type | ENCRYPTION_FLAG,
        unique_id=index,
        timestamp=0,
        original_timestamp=0,
        name=name,
        data=encrypt_beyond_payload(plain, seed),
    )


def seed_helper_or_skip() -> pathlib.Path:
    helper = build_seed_helper(pathlib.Path("seed_finder"), pathlib.Path("seed_finder.c"))
    if helper is None or not helper.exists():
        pytest.skip("seed_finder helper unavailable")
    return helper


def test_seed_pattern_falls_back_to_base_type_for_extensionless_name():
    entry = RscEntry(
        index=1,
        source="test",
        entry_type=0x03 | ENCRYPTION_FLAG,
        unique_id=1,
        timestamp=0,
        original_timestamp=0,
        name="resource_without_suffix",
        data=b"x",
    )
    assert seed_pattern_for_entry(entry) == PNG_SIG


def test_recover_encryption_seeds_handles_non_monotonic_seed_order():
    helper = seed_helper_or_skip()
    plain = PNG_SIG + b"non-monotonic-seed-check"
    first_seed = 0x000100AA
    second_seed = 0x000010BB

    first = make_entry(10, "first.dmi", 0x03, first_seed, plain)
    second = make_entry(11, "second.dmi", 0x03, second_seed, plain)

    seeds = recover_encryption_seeds([first, second], helper)
    assert seeds.get(first.index) == first_seed
    assert seeds.get(second.index) == second_seed
    assert decrypt_beyond_payload(first.data, first_seed) == plain
    assert decrypt_beyond_payload(second.data, second_seed) == plain


def test_recover_encryption_seeds_uses_base_type_fallback_for_extensionless_entry():
    helper = seed_helper_or_skip()
    plain = PNG_SIG + b"extensionless-entry"
    seed = 0x000020CC
    entry = make_entry(25, "no_suffix_entry", 0x03, seed, plain)

    seeds = recover_encryption_seeds([entry], helper)
    assert seeds.get(entry.index) == seed
    assert decrypt_beyond_payload(entry.data, seed) == plain
