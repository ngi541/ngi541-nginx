from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


BENCHMARK_DIR = Path(__file__).resolve().parents[2]
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

from framework.environment import (
    collect_cpu,
    collect_memory,
    collect_network,
    collect_system,
)
from framework.provenance import (
    git_source_info,
    record_binaries,
    sha256_file,
)


class EnvironmentTests(unittest.TestCase):
    def test_system_inventory_is_normalized(self):
        data = collect_system()
        self.assertEqual(data["schema_version"], 1)
        self.assertIn("os", data)
        self.assertIn("architecture", data)
        self.assertIn("python", data)

    def test_cpu_inventory_has_isa_contract(self):
        data = collect_cpu()
        self.assertEqual(data["schema_version"], 1)
        self.assertIn("topology", data)
        self.assertIn("isa", data)
        self.assertIn("aes", data["isa"])
        self.assertIn("avx2", data["isa"])

    def test_memory_inventory(self):
        data = collect_memory()
        self.assertEqual(data["schema_version"], 1)
        self.assertIn("total_bytes", data)

    def test_network_inventory(self):
        data = collect_network()
        self.assertEqual(data["schema_version"], 1)
        self.assertIsInstance(data["interfaces"], list)


@unittest.skipUnless(shutil.which("git"), "git is required")
class ProvenanceTests(unittest.TestCase):
    def _git_repo(self, root: Path) -> Path:
        repo = root / "source"
        repo.mkdir()

        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=repo,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo,
            check=True,
        )

        (repo / "file.txt").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "initial"],
            cwd=repo,
            check=True,
        )
        return repo

    def test_git_source_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._git_repo(root)

            info = git_source_info("source", repo, root)
            self.assertEqual(len(info["commit"]), 40)
            self.assertFalse(info["tracked_dirty"])

    def test_file_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.bin"
            path.write_bytes(b"ngi541")

            expected = hashlib.sha256(b"ngi541").hexdigest()
            self.assertEqual(sha256_file(path), expected)

    def test_binary_record_has_no_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "artifact.bin"
            artifact.write_bytes(b"ngi541")

            output = root / "binaries.sha256"
            record = record_binaries(
                root,
                [f"engine={artifact}"],
                output,
            )

            self.assertEqual(
                record["artifacts"][0]["location"],
                "artifact.bin",
            )
            self.assertNotIn(
                str(root),
                output.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
