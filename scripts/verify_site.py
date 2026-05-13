#!/usr/bin/env python3
"""End-to-end site verification for ai-bob-setup-agent GitHub Pages.

Runs a step-by-step audit of all HTML pages, confirming each check passes
before proceeding to the next. Uses AIGovOps Foundation logging style:
governance-as-code evidence with structured pass/fail verdicts.

Usage:
    python scripts/verify_site.py               # from repo root
    python scripts/verify_site.py --verbose      # show passing details
    python scripts/verify_site.py --fix-hints    # suggest fixes for failures

Exit codes:
    0  — all checks passed
    1  — one or more checks failed
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ── AIGovOps Foundation Logging ─────────────────────────────────────────────
# Structured, auditable, evidence-based. Every check produces a verdict.

REPO_ROOT = Path(__file__).resolve().parent.parent

# ANSI colours
C_RESET = "\033[0m"
C_GREEN = "\033[32m"
C_RED = "\033[31m"
C_YELLOW = "\033[33m"
C_BLUE = "\033[34m"
C_DIM = "\033[2m"
C_BOLD = "\033[1m"

# Disable colours if not a TTY
if not sys.stdout.isatty():
    C_RESET = C_GREEN = C_RED = C_YELLOW = C_BLUE = C_DIM = C_BOLD = ""


@dataclass
class CheckResult:
    """A single governance check verdict."""

    step: str
    passed: bool
    message: str
    evidence: list[str] = field(default_factory=list)
    fix_hint: str = ""


@dataclass
class StepResult:
    """A governance step containing multiple checks."""

    name: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)


class GovOpsLogger:
    """AIGovOps Foundation audit logger.

    Follows the Foundation's core principle: evidence over intention.
    Every check produces a structured verdict that can be audited.
    """

    def __init__(self, verbose: bool = False, fix_hints: bool = False) -> None:
        self.verbose = verbose
        self.fix_hints = fix_hints
        self.steps: list[StepResult] = []
        self._current_step: StepResult | None = None

    def banner(self) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"\n{C_BOLD}{'═' * 72}{C_RESET}")
        print(f"{C_BOLD}  AIGovOps Foundation — Site Verification Audit{C_RESET}")
        print(f"{C_DIM}  Governance as Code · Evidence over Intention{C_RESET}")
        print(f"{C_DIM}  {ts}{C_RESET}")
        print(f"{C_BOLD}{'═' * 72}{C_RESET}\n")

    def begin_step(self, name: str) -> None:
        """Start a new governance step. Confirms previous step passed first."""
        # Gate: if the previous step failed, halt the pipeline
        if self._current_step and not self._current_step.passed:
            self._print_step_summary(self._current_step)
            print(
                f"\n{C_RED}{C_BOLD}  ✗ PIPELINE HALTED{C_RESET}"
                f" — Step '{self._current_step.name}' failed. "
                f"Fix before proceeding.\n"
            )
            self._print_final_summary()
            sys.exit(1)

        if self._current_step:
            self._print_step_summary(self._current_step)

        self._current_step = StepResult(name=name)
        self.steps.append(self._current_step)
        print(f"\n{C_BLUE}{C_BOLD}  ┌─ Step {len(self.steps)}: {name}{C_RESET}")

    def check(self, result: CheckResult) -> None:
        """Record a check result."""
        assert self._current_step, "Must call begin_step() before check()"
        self._current_step.checks.append(result)

        if result.passed:
            if self.verbose:
                print(f"  {C_GREEN}│  ✓ {result.step}: {result.message}{C_RESET}")
                for ev in result.evidence:
                    print(f"  {C_DIM}│    ↳ {ev}{C_RESET}")
        else:
            print(f"  {C_RED}│  ✗ {result.step}: {result.message}{C_RESET}")
            for ev in result.evidence:
                print(f"  {C_DIM}│    ↳ {ev}{C_RESET}")
            if self.fix_hints and result.fix_hint:
                print(f"  {C_YELLOW}│    💡 {result.fix_hint}{C_RESET}")

    def _print_step_summary(self, step: StepResult) -> None:
        icon = f"{C_GREEN}✓" if step.passed else f"{C_RED}✗"
        print(
            f"  {icon} └─ {step.name}: "
            f"{step.pass_count}/{len(step.checks)} passed{C_RESET}"
        )

    def finish(self) -> bool:
        """Finalize the audit and print summary. Returns True if all passed."""
        if self._current_step:
            self._print_step_summary(self._current_step)
        self._print_final_summary()
        return all(s.passed for s in self.steps)

    def _print_final_summary(self) -> None:
        total_checks = sum(len(s.checks) for s in self.steps)
        total_pass = sum(s.pass_count for s in self.steps)
        total_fail = sum(s.fail_count for s in self.steps)
        all_ok = total_fail == 0

        print(f"\n{C_BOLD}{'─' * 72}{C_RESET}")
        if all_ok:
            print(
                f"{C_GREEN}{C_BOLD}"
                f"  ✓ AUDIT PASSED — {total_checks} checks, "
                f"{total_pass} passed, 0 failed"
                f"{C_RESET}"
            )
        else:
            print(
                f"{C_RED}{C_BOLD}"
                f"  ✗ AUDIT FAILED — {total_checks} checks, "
                f"{total_pass} passed, {total_fail} failed"
                f"{C_RESET}"
            )
        print(f"{C_BOLD}{'─' * 72}{C_RESET}\n")


# ── Page inventory ──────────────────────────────────────────────────────────

ALL_PAGES = [
    "index.html",
    "bizplan.html",
    "pitch.html",
    "prdfaq.html",
    "userguide.html",
    "install.html",
    "toolstack.html",
    "howibuilt.html",
    "config.html",
    "dashboard.html",
    "foundation.html",
]

# pitch.html is a dark-themed deck with minimal nav and no footer
PAGES_WITH_FOOTER = [p for p in ALL_PAGES if p != "pitch.html"]

CANONICAL_NAV_LINKS = [
    "bizplan.html",
    "pitch.html",
    "prdfaq.html",
    "userguide.html",
    "install.html",
    "toolstack.html",
    "howibuilt.html",
    "config.html",
    "dashboard.html",
    "foundation.html",
]

CANONICAL_FOOTER_DOCS = [
    "bizplan.html",
    "pitch.html",
    "prdfaq.html",
    "userguide.html",
    "install.html",
    "toolstack.html",
    "howibuilt.html",
    "config.html",
    "dashboard.html",
    "foundation.html",
]


def read_page(name: str) -> str:
    path = REPO_ROOT / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


# ── Step 1: File Existence ──────────────────────────────────────────────────


def step_file_existence(log: GovOpsLogger) -> None:
    log.begin_step("File Existence — All expected pages present")
    for page in ALL_PAGES:
        path = REPO_ROOT / page
        exists = path.exists()
        log.check(
            CheckResult(
                step=page,
                passed=exists,
                message="exists" if exists else "FILE MISSING",
                evidence=[str(path)],
                fix_hint=f"Create {page} following the site template.",
            )
        )

    # Also check style.css
    css_path = REPO_ROOT / "assets" / "style.css"
    log.check(
        CheckResult(
            step="assets/style.css",
            passed=css_path.exists(),
            message="exists" if css_path.exists() else "FILE MISSING",
            evidence=[str(css_path)],
            fix_hint="Ensure assets/style.css exists.",
        )
    )


# ── Step 2: CSS and Font References ─────────────────────────────────────────


def step_css_and_fonts(log: GovOpsLogger) -> None:
    log.begin_step("CSS & Font References — Shared style system loaded")
    for page in ALL_PAGES:
        content = read_page(page)
        if not content:
            continue

        has_css = "assets/style.css" in content
        log.check(
            CheckResult(
                step=f"{page} → style.css",
                passed=has_css,
                message="linked" if has_css else "MISSING style.css link",
                fix_hint=f'Add <link rel="stylesheet" href="assets/style.css"> to {page}',
            )
        )

        has_fonts = "fonts.googleapis.com" in content
        log.check(
            CheckResult(
                step=f"{page} → Google Fonts",
                passed=has_fonts,
                message="loaded" if has_fonts else "MISSING Google Fonts",
                fix_hint=f"Add Google Fonts <link> to {page} <head>.",
            )
        )


# ── Step 3: Foundation Banner ───────────────────────────────────────────────


def step_foundation_banner(log: GovOpsLogger) -> None:
    log.begin_step("Foundation Banner — AIGovOps branding on every page")
    for page in ALL_PAGES:
        content = read_page(page)
        if not content:
            continue

        has_banner = "foundation-banner" in content
        has_yes = "YES" in content and "Ship AI" in content
        log.check(
            CheckResult(
                step=f"{page} → banner",
                passed=has_banner and has_yes,
                message="present with YES framework"
                if (has_banner and has_yes)
                else f"{'banner ' + ('OK' if has_banner else 'MISSING')}, "
                f"{'YES OK' if has_yes else 'YES MISSING'}",
                fix_hint=f"Add the foundation-banner div to {page}.",
            )
        )


# ── Step 4: Topnav Consistency ──────────────────────────────────────────────


def step_topnav(log: GovOpsLogger) -> None:
    log.begin_step("Topnav — All navigation links present and consistent")
    for page in ALL_PAGES:
        content = read_page(page)
        if not content:
            continue

        # pitch.html has a minimal nav — skip full nav check
        if page == "pitch.html":
            has_foundation = "foundation.html" in content
            log.check(
                CheckResult(
                    step=f"{page} → minimal nav",
                    passed=has_foundation,
                    message="Foundation link present"
                    if has_foundation
                    else "MISSING Foundation link",
                    evidence=["pitch.html uses minimal nav (by design)"],
                )
            )
            continue

        # Extract header section
        header_end = content.find("</header>")
        header = content[: header_end if header_end > 0 else 2000]

        missing = [link for link in CANONICAL_NAV_LINKS if link not in header]
        log.check(
            CheckResult(
                step=f"{page} → nav links",
                passed=len(missing) == 0,
                message=f"all {len(CANONICAL_NAV_LINKS)} links present"
                if not missing
                else f"MISSING: {', '.join(missing)}",
                evidence=missing if missing else [],
                fix_hint=f"Add missing nav links to {page} topnav.",
            )
        )

        # Check GitHub CTA
        has_cta = "github.com/bobrapp/ai-bob-setup-agent" in header
        log.check(
            CheckResult(
                step=f"{page} → GitHub CTA",
                passed=has_cta,
                message="present" if has_cta else "MISSING GitHub CTA button",
                fix_hint=f"Add GitHub CTA button to {page} topnav.",
            )
        )


# ── Step 5: Footer Consistency ──────────────────────────────────────────────


def step_footer(log: GovOpsLogger) -> None:
    log.begin_step("Footer — Complete Docs list and Source links")
    for page in PAGES_WITH_FOOTER:
        content = read_page(page)
        if not content:
            continue

        has_footer = 'class="site-foot"' in content
        if not has_footer:
            log.check(
                CheckResult(
                    step=f"{page} → footer",
                    passed=False,
                    message="MISSING footer element",
                    fix_hint=f"Add <footer class='site-foot'> to {page}.",
                )
            )
            continue

        footer_content = content[content.find('class="site-foot"') :]
        missing = [link for link in CANONICAL_FOOTER_DOCS if link not in footer_content]
        log.check(
            CheckResult(
                step=f"{page} → footer docs",
                passed=len(missing) == 0,
                message=f"all {len(CANONICAL_FOOTER_DOCS)} doc links present"
                if not missing
                else f"MISSING: {', '.join(missing)}",
                evidence=missing if missing else [],
                fix_hint=f"Add missing doc links to {page} footer.",
            )
        )


# ── Step 6: Internal Link Integrity ────────────────────────────────────────


def step_internal_links(log: GovOpsLogger) -> None:
    log.begin_step("Internal Links — No broken references between pages")
    all_files = set(ALL_PAGES)
    all_files.add("assets/style.css")

    for page in ALL_PAGES:
        content = read_page(page)
        if not content:
            continue

        # Find all internal href references (not external, not anchors)
        internal_links = re.findall(r'href="([^"#]+)"', content)
        internal_links = [
            link
            for link in internal_links
            if not link.startswith("http")
            and not link.startswith("mailto:")
            and not link.startswith("//")
        ]

        broken = []
        for link in internal_links:
            # Normalize path
            target = REPO_ROOT / link
            if not target.exists():
                broken.append(link)

        log.check(
            CheckResult(
                step=f"{page} → internal links",
                passed=len(broken) == 0,
                message=f"{len(internal_links)} links, all valid"
                if not broken
                else f"BROKEN: {', '.join(broken)}",
                evidence=broken if broken else [],
                fix_hint=f"Fix broken links in {page}: {', '.join(broken)}"
                if broken
                else "",
            )
        )


# ── Step 7: Brand Tokens ───────────────────────────────────────────────────


def step_brand_tokens(log: GovOpsLogger) -> None:
    log.begin_step("Brand Tokens — Foundation colours in shared stylesheet")
    css_content = (REPO_ROOT / "assets" / "style.css").read_text(encoding="utf-8")

    tokens = {
        "--foundation-navy": "#1B2A4A",
        "--foundation-blue": "#3D8BFF",
        "--foundation-green": "#2BB673",
    }

    for token, expected in tokens.items():
        present = token in css_content
        correct_value = expected.lower() in css_content.lower()
        log.check(
            CheckResult(
                step=f"style.css → {token}",
                passed=present and correct_value,
                message=f"defined as {expected}"
                if (present and correct_value)
                else f"{'present' if present else 'MISSING'}"
                f"{'' if correct_value else f', expected {expected}'}",
                fix_hint=f"Add {token}: {expected}; to :root in style.css.",
            )
        )


# ── Step 8: Dashboard Data Pipeline ────────────────────────────────────────


def step_dashboard_data(log: GovOpsLogger) -> None:
    log.begin_step("Dashboard Data Pipeline — Generator script and JSON")

    # Check generator script exists
    script_path = REPO_ROOT / "scripts" / "generate_dashboard_data.py"
    log.check(
        CheckResult(
            step="generate_dashboard_data.py",
            passed=script_path.exists(),
            message="exists" if script_path.exists() else "MISSING",
            fix_hint="Create scripts/generate_dashboard_data.py.",
        )
    )

    # Check dashboard-data.json exists and is valid
    json_path = REPO_ROOT / "dashboard-data.json"
    json_exists = json_path.exists()
    json_valid = False
    if json_exists:
        import json

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            json_valid = "kpis" in data and "customers" in data and "agents" in data
        except (json.JSONDecodeError, KeyError):
            json_valid = False

    log.check(
        CheckResult(
            step="dashboard-data.json",
            passed=json_exists and json_valid,
            message="valid with kpis, customers, agents"
            if (json_exists and json_valid)
            else f"{'exists but invalid schema' if json_exists else 'MISSING'}",
            fix_hint="Run: python scripts/generate_dashboard_data.py",
        )
    )

    # Check dashboard.html references the JSON
    dash_content = read_page("dashboard.html")
    fetches_json = "dashboard-data.json" in dash_content
    log.check(
        CheckResult(
            step="dashboard.html → JSON fetch",
            passed=fetches_json,
            message="fetches dashboard-data.json"
            if fetches_json
            else "MISSING JSON fetch",
            fix_hint="dashboard.html should fetch('dashboard-data.json').",
        )
    )


# ── Step 9: CI Workflow Integrity ───────────────────────────────────────────


def step_ci_workflow(log: GovOpsLogger) -> None:
    log.begin_step("CI Workflow — Pipeline configuration valid")

    ci_path = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    ci_exists = ci_path.exists()
    log.check(
        CheckResult(
            step="ci.yml",
            passed=ci_exists,
            message="exists" if ci_exists else "MISSING",
            fix_hint="Create .github/workflows/ci.yml.",
        )
    )

    if ci_exists:
        ci_content = ci_path.read_text(encoding="utf-8")

        # Check key CI steps
        steps_expected = {
            "ruff check": "Ruff lint" in ci_content or "ruff check" in ci_content,
            "ruff format": "ruff format" in ci_content,
            "pytest": "pytest" in ci_content,
            "dry-run install": "install.sh" in ci_content or "dry-run" in ci_content,
        }

        for step_name, present in steps_expected.items():
            log.check(
                CheckResult(
                    step=f"ci.yml → {step_name}",
                    passed=present,
                    message="configured" if present else "MISSING",
                    fix_hint=f"Add {step_name} step to ci.yml.",
                )
            )

    # Check deploy workflow
    deploy_path = REPO_ROOT / ".github" / "workflows" / "deploy-pages.yml"
    log.check(
        CheckResult(
            step="deploy-pages.yml",
            passed=deploy_path.exists(),
            message="exists" if deploy_path.exists() else "MISSING",
            fix_hint="Create .github/workflows/deploy-pages.yml.",
        )
    )


# ── Step 10: Install Script ────────────────────────────────────────────────


def step_install_script(log: GovOpsLogger) -> None:
    log.begin_step("Install Script — Deployment entry point valid")

    install_path = REPO_ROOT / "install.sh"
    exists = install_path.exists()
    log.check(
        CheckResult(
            step="install.sh",
            passed=exists,
            message="exists" if exists else "MISSING",
            fix_hint="Create install.sh in the repo root.",
        )
    )

    if exists:
        content = install_path.read_text(encoding="utf-8")

        is_executable = os.access(install_path, os.X_OK)
        has_shebang = content.startswith("#!/")
        has_dry_run = "--dry-run" in content

        log.check(
            CheckResult(
                step="install.sh → executable",
                passed=is_executable or has_shebang,
                message="executable"
                if is_executable
                else ("has shebang" if has_shebang else "NOT executable"),
                fix_hint="Run: chmod +x install.sh",
            )
        )

        log.check(
            CheckResult(
                step="install.sh → --dry-run",
                passed=has_dry_run,
                message="supports --dry-run"
                if has_dry_run
                else "MISSING --dry-run support",
                fix_hint="Add --dry-run flag handling to install.sh.",
            )
        )


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AIGovOps Foundation — Site Verification Audit"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show passing check details"
    )
    parser.add_argument(
        "--fix-hints", action="store_true", help="Show fix suggestions for failures"
    )
    args = parser.parse_args()

    log = GovOpsLogger(verbose=args.verbose, fix_hints=args.fix_hints)
    log.banner()

    # Each step gates the next — if a step fails, the pipeline halts.
    # This ensures governance evidence is built incrementally.
    step_file_existence(log)
    step_css_and_fonts(log)
    step_foundation_banner(log)
    step_topnav(log)
    step_footer(log)
    step_internal_links(log)
    step_brand_tokens(log)
    step_dashboard_data(log)
    step_ci_workflow(log)
    step_install_script(log)

    all_passed = log.finish()
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
