"""Regression checks for real stage-0 tooling; no platform behavior is simulated."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RepositoryChecksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cloudpilot-check-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        result = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            check=True,
            capture_output=True,
        )
        for name in set(result.stdout.decode().strip("\0").split("\0")) - {""}:
            source = ROOT / name
            if source.is_file():
                dest = self.root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
        self.git("init", "-b", "main")
        self.git("add", ".")

    def git(self, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True,
            capture_output=True,
        )

    def run_checker(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.root / "scripts/check_repository.py")],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_clean_repository_passes(self) -> None:
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_architecture_is_rejected(self) -> None:
        (self.root / "docs/architecture/overview.md").unlink()
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing file: docs/architecture/overview.md", result.stderr)

    def test_broken_markdown_link_is_rejected(self) -> None:
        with (self.root / "README.md").open("a") as stream:
            stream.write("\n[Missing](docs/missing.md)\n")
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Markdown link", result.stderr)

    def test_staged_secret_is_detected_after_worktree_cleanup(self) -> None:
        path = self.root / "leak.txt"
        token = "ghp_" + "a" * 40
        path.write_text(token + "\n")
        self.git("add", "leak.txt")
        path.write_text("sanitized\n")
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("index:leak.txt: possible GitHub token", result.stderr)
        self.assertNotIn(token, result.stderr)

    def test_force_added_env_is_rejected(self) -> None:
        (self.root / ".env").write_text("LOCAL_FLAG=1\n")
        self.git("add", "--force", ".env")
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forbidden staged path", result.stderr)


if __name__ == "__main__":
    unittest.main()
