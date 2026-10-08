from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


BENCHMARK_DIR = Path(__file__).resolve().parents[2]
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

from framework.io_utils import FrameworkError
from workloads.http3.adapter import (
    _nginx_config,
    _write_payload,
    resolve_http3_config,
)


class Http3ResolveTests(unittest.TestCase):
    def test_defaults_are_resolved(self):
        request = {
            "workload": "http3",
            "environment": "local",
            "variants": ["stock", "ngi541-direct"],
            "parameters": {"repetitions": 2},
        }
        common = {
            "workload": "http3",
            "environment": "local",
            "variants": ["stock", "ngi541-direct"],
            "parameters": {"repetitions": 2},
            "comparison": {
                "mode": "paired-balanced",
                "random_seed": None,
            },
        }

        resolved = resolve_http3_config(request, common)
        params = resolved["parameters"]

        self.assertEqual(params["payload_bytes"], [16384])
        self.assertEqual(params["workers"], [1])
        self.assertEqual(params["clients"], [1])
        self.assertEqual(params["requests_per_client"], 5000)
        self.assertEqual(params["warmup_requests_per_client"], 50)
        self.assertEqual(
            params["cipher_suite"],
            "TLS_AES_128_GCM_SHA256",
        )

    def test_invalid_axis_rejected(self):
        request = {
            "workload": "http3",
            "environment": "local",
            "variants": ["stock"],
            "parameters": {},
        }
        common = {
            "workload": "http3",
            "environment": "local",
            "variants": ["stock"],
            "parameters": {
                "repetitions": 1,
                "clients": [0],
            },
            "comparison": {
                "mode": "single",
                "random_seed": None,
            },
        }

        with self.assertRaises(FrameworkError):
            resolve_http3_config(request, common)


class Http3PayloadTests(unittest.TestCase):
    def test_historical_1k_payload_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "1024.bin"
            digest = _write_payload(path, 1024)
            self.assertEqual(
                digest,
                "5f70bf18a086007016e948b04aed3b82103a36bea41755b6cddfaf10ace3c6ef",
            )

    def test_historical_16k_payload_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "16384.bin"
            digest = _write_payload(path, 16384)
            self.assertEqual(
                digest,
                "4fe7b59af6de3b665b67788cc2f99892ab827efae3a467342b3bb4e3bc8e5bfe",
            )


class Http3ConfigTests(unittest.TestCase):
    def test_multiworker_uses_reuseport(self):
        config = _nginx_config(
            workers=2,
            host="127.0.0.1",
            port=8443,
            worker_connections=4096,
            keepalive_requests=20000,
        )
        self.assertIn(
            "listen 127.0.0.1:8443 quic reuseport;",
            config,
        )

    def test_single_worker_does_not_use_reuseport(self):
        config = _nginx_config(
            workers=1,
            host="127.0.0.1",
            port=8443,
            worker_connections=4096,
            keepalive_requests=20000,
        )
        self.assertIn(
            "listen 127.0.0.1:8443 quic;",
            config,
        )
        self.assertNotIn("quic reuseport", config)


if __name__ == "__main__":
    unittest.main()
