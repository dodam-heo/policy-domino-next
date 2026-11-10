"""Architectural boundaries that prevent returning to the v2/v3/v4 patchwork."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SubmissionArchitectureTests(unittest.TestCase):
    def test_one_production_workflow(self):
        workflows = sorted((ROOT / ".github/workflows").glob("*.yml"))
        self.assertEqual([x.name for x in workflows], ["pipeline.yml"])

    def test_pages_deployment_cannot_block_official_collection(self):
        workflow = (ROOT / ".github/workflows/pipeline.yml").read_text(
            encoding="utf-8")
        refresh = workflow.split("  collect_and_refresh:\n", 1)[1].split(
            "  publish:\n", 1)[0]
        publish = workflow.split("  publish:\n", 1)[1]
        self.assertIn("needs: verify", refresh)
        self.assertNotIn("needs: publish", refresh)
        self.assertNotIn("actions/deploy-pages@", refresh)
        self.assertIn("github.event_name == 'schedule'", refresh)
        self.assertIn("github.event_name == 'workflow_dispatch'", refresh)
        self.assertEqual(workflow.count("uses: actions/deploy-pages@"), 1)
        self.assertIn("needs: [verify, collect_and_refresh]", publish)
        self.assertIn("needs.verify.result == 'success'", publish)
        self.assertIn("needs.collect_and_refresh.result == 'skipped'", publish)
        self.assertIn("timeout-minutes: 25", publish)
        self.assertIn("timeout: '1200000'", publish)
        self.assertIn("actions/deploy-pages@v5", publish)
        self.assertIn("actions/checkout@v5", workflow)
        self.assertIn("actions/setup-python@v6", workflow)
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}",
                      workflow)

    def test_html_does_not_mix_application_programming_and_css(self):
        html = (ROOT / "site/index.html").read_text(encoding="utf-8")
        self.assertIn('href="./styles.css"', html)
        self.assertIn('src="./app.js"', html)
        self.assertNotIn("<style>", html)
        self.assertFalse(re.search(r"<script(?![^>]+src=)", html))

    def test_backend_never_imports_frontend_or_legacy_versions(self):
        sources = (ROOT / "policy_domino").glob("*.py")
        for path in sources:
            code = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotRegex(code, r"(?m)^\s*(from|import)\s+(v2|v3|v4|watch|impact_scanner)\b")
                self.assertNotIn("site/app.js", code)

    def test_release_and_renderer_use_exactly_one_contract(self):
        pipeline = (ROOT / "policy_domino/pipeline.py").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/pipeline.yml").read_text(encoding="utf-8")
        self.assertIn("validate_public(data)", pipeline)
        self.assertIn("python -m policy_domino.contracts site/data.json", workflow)

    def test_one_event_projection_and_evidence_first_interface(self):
        workflow = (ROOT / ".github/workflows/pipeline.yml").read_text(encoding="utf-8")
        events = (ROOT / "policy_domino/events.py").read_text(encoding="utf-8")
        pipeline = (ROOT / "policy_domino/pipeline.py").read_text(encoding="utf-8")
        frontend = (ROOT / "site/app.js").read_text(encoding="utf-8")
        index = (ROOT / "site/index.html").read_text(encoding="utf-8")
        self.assertIn("events = build_events(", pipeline)
        self.assertIn('"events": events', pipeline)
        self.assertIn("def event_identity(", events)
        self.assertIn("def build_events(", events)
        self.assertIn("python -m policy_domino render", workflow)
        self.assertIn("python -m policy_domino ai --limit 24", workflow)
        for key in ("mode-all", "mode-new", "mode-amended",
                    "mode-repealed", "mode-impact", "stat-events",
                    "stat-agencies", "analysis-coverage"):
            self.assertIn('id="' + key + '"', index)
        for obsolete in ("kind-filter", "topic-filter", "impact-filter", "mode-benefit"):
            self.assertNotIn('id="' + obsolete + '"', index)
        self.assertNotIn("급여·지원기준", index)
        self.assertIn("영향도 큼", index)
        self.assertIn("highImpactScope",
                      (ROOT / "site/presentation.js").read_text(encoding="utf-8"))
        self.assertNotIn('agencyFilter', frontend)
        self.assertNotIn("legacy_source.json", events)
        self.assertNotIn("policy_domino.engine", events)

    def test_code_quality_spec_does_not_pretend_all_impact_is_implemented(self):
        standard = (ROOT / "docs/ENGINEERING_STANDARD.md").read_text(encoding="utf-8")
        self.assertIn("미완성", standard)
        self.assertIn("공식 사업", standard)
        self.assertIn("범용성", standard)


if __name__ == "__main__":
    unittest.main()
