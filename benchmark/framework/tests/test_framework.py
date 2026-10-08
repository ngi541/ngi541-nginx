from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


BENCHMARK_DIR = Path(__file__).resolve().parents[2]
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

from framework.ids import EXPERIMENT_ID_RE, generate_experiment_id
from framework.io_utils import (
    FrameworkError,
    atomic_write_json,
    write_immutable_json,
)
from framework.lifecycle import initial_state, transition
from framework.schedule import build_schedule, resolve_common_request


class IdTests(unittest.TestCase):
    def test_generated_id_matches_contract(self):
        now = datetime(2026, 10, 9, 21, 45, 12, tzinfo=timezone.utc)
        result = generate_experiment_id(
            "http3",
            "local",
            now=now,
            short_id="a31f92",
        )
        self.assertEqual(
            result,
            "http3-local-20261009T214512Z-a31f92",
        )
        self.assertRegex(result, EXPERIMENT_ID_RE)


class ImmutableWriteTests(unittest.TestCase):
    def test_identical_immutable_write_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "value.json"
            value = {"b": 2, "a": 1}
            write_immutable_json(path, value)
            write_immutable_json(path, value)

    def test_different_immutable_write_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "value.json"
            write_immutable_json(path, {"value": 1})
            with self.assertRaises(FrameworkError):
                write_immutable_json(path, {"value": 2})


class LifecycleTests(unittest.TestCase):
    def test_created_to_preparing(self):
        with tempfile.TemporaryDirectory() as tmp:
            exp = Path(tmp)
            (exp / "logs").mkdir()
            atomic_write_json(
                exp / "state.json",
                initial_state("http3-local-20261009T214512Z-a31f92"),
            )
            result = transition(exp, "PREPARING")
            self.assertEqual(result["state"], "PREPARING")

    def test_illegal_transition_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            exp = Path(tmp)
            (exp / "logs").mkdir()
            atomic_write_json(
                exp / "state.json",
                initial_state("http3-local-20261009T214512Z-a31f92"),
            )
            with self.assertRaises(FrameworkError):
                transition(exp, "RUNNING")


class ScheduleTests(unittest.TestCase):
    def _request(self):
        return {
            "workload": "http3",
            "environment": "local",
            "variants": ["stock", "ngi541-direct"],
            "parameters": {
                "payload_bytes": [1024, 16384],
                "workers": [2],
                "clients": [16],
                "repetitions": 2,
                "warmup_requests_per_client": 50,
            },
        }

    def test_paired_balanced_schedule(self):
        resolved = resolve_common_request(self._request())
        schedule = build_schedule(
            "http3-local-20261009T214512Z-a31f92",
            resolved,
        )

        self.assertEqual(schedule["comparison_mode"], "paired-balanced")
        self.assertEqual(len(schedule["runs"]), 8)

        first = schedule["runs"][0:2]
        second = schedule["runs"][2:4]

        self.assertEqual(
            [run["variant"] for run in first],
            ["stock", "ngi541-direct"],
        )
        self.assertEqual(
            [run["variant"] for run in second],
            ["ngi541-direct", "stock"],
        )

    def test_matrix_is_deterministic(self):
        resolved = resolve_common_request(self._request())
        one = build_schedule(
            "http3-local-20261009T214512Z-a31f92",
            resolved,
        )
        two = build_schedule(
            "http3-local-20261009T214512Z-a31f92",
            resolved,
        )
        self.assertEqual(one, two)

    def test_paired_balanced_requires_two_variants(self):
        request = self._request()
        request["variants"] = [
            "stock",
            "ngi541-direct",
            "ngi541-provider",
        ]
        request["comparison"] = {"mode": "paired-balanced"}

        with self.assertRaises(FrameworkError):
            resolve_common_request(request)


if __name__ == "__main__":
    unittest.main()
