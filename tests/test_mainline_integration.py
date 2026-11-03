"""Prevent a green stacked PR from being mistaken for a mainline feature release."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MainlineIntegrationContract(unittest.TestCase):
    def test_research_implementation_and_product_docs_coexist(self):
        required = (
            "research_workspace/__init__.py",
            "research_workspace/__main__.py",
            "research_workspace/research.py",
            "research_workspace/fetcher.py",
            "research_workspace/extraction.py",
            "research_workspace/store.py",
            "research_workspace/server.py",
            "research_workspace/monitoring.py",
            "apps/evidence-demo/live.html",
            "apps/evidence-demo/live.css",
            "apps/evidence-demo/src/live.js",
            "tests/test_research_workspace.py",
            "tests/test_continuous_research.py",
            "tests/fixtures/research_goldens.json",
            "tests/fixtures/monitoring_goldens.json",
            "docs/product/VOICE_OF_CUSTOMER_2026.md",
            "docs/product/PRD_V0.2_EVIDENCE_RADAR.md",
            "docs/product/VALIDATION_AND_LAUNCH.md",
            "docs/product/README.md",
            "docs/V0.2_B_IMPLEMENTATION.md",
            "docs/V0.3_CONTINUOUS_RESEARCH.md",
            "docs/V0.4_MAINLINE_INTEGRATION.md",
        )
        missing = [path for path in required if not (ROOT / path).is_file()]
        self.assertFalse(missing, f"Mainline release is missing: {missing}")

    def test_demo_entry_links_to_live_workspace(self):
        html = (ROOT / "apps/evidence-demo/index.html").read_text("utf-8")
        self.assertIn('href="./live.html"', html)
        self.assertIn('id="research-app"', html)
        live_html = (ROOT / "apps/evidence-demo/live.html").read_text("utf-8")
        self.assertIn('src="./src/live.js"', live_html)
        live_script = (ROOT / "apps/evidence-demo/src/live.js").read_text("utf-8")
        self.assertIn("/api/v1/projects", live_script)

    def test_package_declares_cli_and_research_package(self):
        config = (ROOT / "pyproject.toml").read_text("utf-8")
        self.assertIn('evidence-radar-local = "research_workspace.__main__:main"', config)
        self.assertIn('include = ["research_workspace*"]', config)
        proc = subprocess.run(
            [sys.executable, "-m", "research_workspace", "--help"],
            cwd=ROOT, capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--allow-host", proc.stdout)
        self.assertIn("tick", proc.stdout)

    def test_sqlite_schema_migration_exists(self):
        from research_workspace.store import ResearchStore
        with tempfile.TemporaryDirectory() as tmp:
            store = ResearchStore(Path(tmp) / "integration.sqlite3")
            with store.db() as db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                tables = {row["name"] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(version, 3)
            self.assertTrue({"projects", "runs", "run_sources", "snapshots",
                             "claims", "research_schedules", "research_changes",
                             "research_reconciliations", "users", "workspaces",
                             "workspace_memberships", "legacy_owner_bindings",
                             "membership_audit"}.issubset(tables))


if __name__ == "__main__":
    unittest.main()
