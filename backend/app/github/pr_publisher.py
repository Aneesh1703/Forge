"""
Phase 10D: GitHub PR Publisher Service
Formats Markdown PR descriptions and publishes Pull Requests via GitHub REST API.
"""

import json
import logging
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from app.agents.coder.models import CodePatch
from app.agents.coder.repo_gate import FinalGateResult
from app.agents.coder.reviewer import ReviewResult
from app.agents.plan_models import ImplementationPlan
from app.execution.models import TestResult
from app.github.auth import CompositeGitHubAuth, GitHubAuthProvider

logger = logging.getLogger(__name__)


@dataclass
class PRRequest:
    """Immutable payload container for GitHub PR creation."""

    owner: str
    repo: str
    head_branch: str
    base_branch: str = "main"
    title: str = ""
    body: str = ""
    draft: bool = False
    labels: list[str] = field(default_factory=list)


class PRPublisher:
    """GitHub REST API publisher for automated pull request creation."""

    def __init__(
        self,
        auth_provider: GitHubAuthProvider | None = None,
        api_base_url: str = "https://api.github.com",
    ) -> None:
        self.auth_provider = auth_provider or CompositeGitHubAuth()
        self.api_base_url = api_base_url.rstrip("/")

    @classmethod
    def format_pr_body(
        cls,
        plan: ImplementationPlan,
        patch: CodePatch,
        test_result: TestResult | None = None,
        repo_gate_result: FinalGateResult | None = None,
        review_result: ReviewResult | None = None,
        test_run: dict[str, Any] | None = None,
    ) -> str:
        """The PR description: the approved plan, what changed against it, and the checks.

        test_run is a JobState.test_results entry, used when no TestResult is at hand
        (e.g. publishing a job resumed from disk).
        """
        changed = set(patch.files_changed)
        lines = ["## Summary", "", plan.summary.strip() or "Resolve repository issue", ""]
        if plan.rationale:
            lines += [plan.rationale.strip(), ""]

        lines += ["## Plan", "", "| Action | File | Symbols | Changed |", "|---|---|---|---|"]
        for fa in plan.file_actions:
            symbols = ", ".join(f"`{s}`" for s in fa.target_symbols) or "—"
            mark = "✅" if fa.file_path in changed else "—"
            lines.append(f"| {fa.action_type.value} | `{fa.file_path}` | {symbols} | {mark} |")
        lines.append("")
        if plan.tasks:
            lines += [
                f"{t.step_number}. **{t.title}** — {t.description}"
                for t in sorted(plan.tasks, key=lambda t: t.step_number)
            ]
            lines.append("")

        lines += ["## Scope", ""] + _scope_lines(plan, changed) + [""]
        lines += ["## Tests", ""] + _test_lines(plan, test_result, test_run) + [""]

        symbols_changed = sorted(
            {h.target_symbol.qualified_symbol_name for h in patch.hunks if h.target_symbol}
        )
        if symbols_changed:
            lines += ["## Symbols changed", ""] + [f"- `{s}`" for s in symbols_changed] + [""]

        checks = []
        if repo_gate_result is not None:
            status = "✅ PASS" if repo_gate_result.passed else "❌ FAIL"
            checks.append(f"- **Repository gate (secrets, debug code)**: {status}")
        if review_result is not None:
            checks.append(f"- **Review**: {review_result.decision.value}")
        if checks:
            lines += ["## Checks", ""] + checks + [""]

        lines += [
            "---",
            "### 🤖 Powered by Forge Engine",
            "*This pull request was generated from an approved plan and verified by Forge.*",
        ]
        return "\n".join(lines)

    def publish_pr(self, request: PRRequest) -> str:
        """Sends HTTP request to GitHub REST API to publish the Pull Request."""
        token = self.auth_provider.get_token()
        if not token:
            raise RuntimeError(
                "GitHub authentication failed: No valid GITHUB_TOKEN or 'gh' CLI token found."
            )

        url = f"{self.api_base_url}/repos/{request.owner}/{request.repo}/pulls"
        payload = {
            "title": request.title,
            "body": request.body,
            "head": request.head_branch,
            "base": request.base_branch,
            "draft": request.draft,
        }

        req_data = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "Forge-Engine-Agent",
        }

        req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req) as resp:
                response_data = json.loads(resp.read().decode("utf-8"))
                html_url = str(response_data.get("html_url", ""))
                logger.info(f"Successfully published PR to GitHub: {html_url}")
                return html_url
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            logger.error(f"GitHub API Error {e.code}: {err_body}")
            raise RuntimeError(f"GitHub API PR publication failed ({e.code}): {err_body}") from e


def _scope_lines(plan: ImplementationPlan, changed: set[str]) -> list[str]:
    """Planned files vs changed files. The safety gate already refuses unplanned files,
    so "outside the plan" only appears for patches built before that rule existed."""
    outside = sorted(changed - plan.allowed_files)
    untouched = sorted(fa.file_path for fa in plan.file_actions if fa.file_path not in changed)
    if not outside and not untouched:
        return ["✅ Every planned file changed, and nothing outside the plan."]
    lines = []
    if outside:
        lines.append("⚠️ Changed outside the plan: " + ", ".join(f"`{f}`" for f in outside))
    if untouched:
        lines.append("ℹ️ Planned but not changed: " + ", ".join(f"`{f}`" for f in untouched))
    return lines


def _test_lines(
    plan: ImplementationPlan, test_result: TestResult | None, test_run: dict[str, Any] | None
) -> list[str]:
    planned = ", ".join(f"`{t}`" for t in plan.test_targets) or "_none selected_"
    lines = [f"- **Planned test targets**: {planned}"]
    ran: list[str] = []
    if test_result is not None:
        passed, total = test_result.passed, test_result.total_tests
    elif test_run is not None:
        passed, total = bool(test_run.get("passed")), int(test_run.get("total_tests") or 0)
        ran = [str(t) for t in test_run.get("test_targets") or []]
    else:
        return lines + ["- **Result**: not recorded"]
    if ran:
        lines.append("- **Ran**: " + ", ".join(f"`{t}`" for t in ran))
    status = "✅ PASS" if passed else "❌ FAIL"
    lines.append(f"- **Result**: {status}" + (f" ({total} tests)" if total else ""))
    return lines
