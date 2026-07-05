from __future__ import annotations

import compileall
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "docs" / "QA_REPORT.md"

KEY_FILES_AND_DIRS = [
    "README.md",
    "requirements.txt",
    "api/main.py",
    "api_server.py",
    "main.py",
    "frontend/package.json",
    "frontend/src/App.tsx",
    "workspace/snapshots",
    "outputs",
]

SCAN_TARGETS = [
    "README.md",
    "docs",
    "api",
    "src",
    "frontend/src",
    ".env.example",
    "frontend/.env.example",
]

TOKEN_PATTERNS = [
    ("GitHub classic token", re.compile(r"ghp_[A-Za-z0-9_]{8,}")),
    ("GitHub fine-grained token", re.compile(r"github_pat_[A-Za-z0-9_]{8,}")),
    ("OpenAI-style token", re.compile(r"sk-[A-Za-z0-9_-]{8,}")),
    ("OPENAI_API_KEY", re.compile(r"OPENAI_API_KEY\s*=\s*(\S+)")),
    (
        "GITHUB_PERSONAL_ACCESS_TOKEN",
        re.compile(r"GITHUB_PERSONAL_ACCESS_TOKEN\s*=\s*(\S+)"),
    ),
]

DATE_DIR_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class CheckResult:
    name: str
    passed: bool
    details: list[str] = field(default_factory=list)


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def truncate_secret(value: str) -> str:
    clean = value.strip()
    if len(clean) <= 10:
        return clean[:3] + "..."
    return clean[:8] + "..." + clean[-4:]


def iter_scan_files() -> list[Path]:
    files: list[Path] = []
    for target in SCAN_TARGETS:
        path = PROJECT_ROOT / target
        if not path.exists():
            continue
        if path.is_file():
            if path.name != ".env":
                files.append(path)
            continue
        for child in path.rglob("*"):
            if child.is_file() and child.name != ".env":
                files.append(child)
    return sorted(set(files))


def check_key_files() -> CheckResult:
    missing = [item for item in KEY_FILES_AND_DIRS if not (PROJECT_ROOT / item).exists()]
    details = ["All key files and directories exist."] if not missing else missing
    return CheckResult("Key files", not missing, details)


def check_sensitive_info() -> CheckResult:
    findings: list[str] = []
    for path in iter_scan_files():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            for label, pattern in TOKEN_PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                token = match.group(1) if match.lastindex else match.group(0)
                if token.strip() in {"", '""', "''"}:
                    continue
                findings.append(
                    f"{relative(path)}:{line_number} {label} {truncate_secret(token)}"
                )
    details = ["No sensitive token patterns found."] if not findings else findings
    return CheckResult("Sensitive information", not findings, details)


def check_python_compile() -> CheckResult:
    targets = [
        PROJECT_ROOT / "api",
        PROJECT_ROOT / "src",
        PROJECT_ROOT / "main.py",
        PROJECT_ROOT / "api_server.py",
    ]
    ok = True
    details: list[str] = []
    for target in targets:
        if not target.exists():
            ok = False
            details.append(f"Missing compile target: {relative(target)}")
            continue
        result = compileall.compile_file(str(target), quiet=1) if target.is_file() else compileall.compile_dir(str(target), quiet=1)
        if result:
            details.append(f"Compiled: {relative(target)}")
        else:
            ok = False
            details.append(f"Compile failed: {relative(target)}")
    return CheckResult("Python compile", ok, details)


def check_frontend_package() -> CheckResult:
    package_path = PROJECT_ROOT / "frontend" / "package.json"
    if not package_path.exists():
        return CheckResult("Frontend package", False, ["frontend/package.json is missing."])

    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return CheckResult("Frontend package", False, [f"Invalid package.json: {exc}"])

    scripts = package.get("scripts", {})
    dependencies = package.get("dependencies", {})
    dev_dependencies = package.get("devDependencies", {})
    all_dependencies = {**dependencies, **dev_dependencies}

    failures: list[str] = []
    if "build" not in scripts:
        failures.append("Missing build script.")
    for dep in ("react", "vite", "lucide-react"):
        if dep not in all_dependencies:
            failures.append(f"Missing dependency: {dep}")

    details = ["Build script and required dependencies are present."] if not failures else failures
    return CheckResult("Frontend package", not failures, details)


def check_local_artifacts() -> CheckResult:
    failures: list[str] = []
    latest_run = PROJECT_ROOT / "workspace" / "runs" / "latest_run.json"
    outputs = PROJECT_ROOT / "outputs"

    if not latest_run.exists():
        failures.append("workspace/runs/latest_run.json is missing.")

    date_dirs = [
        path
        for path in outputs.iterdir()
        if outputs.exists() and path.is_dir() and DATE_DIR_PATTERN.fullmatch(path.name)
    ] if outputs.exists() else []
    if not date_dirs:
        failures.append("outputs has no YYYY-MM-DD directory.")

    index_dirs = [path for path in date_dirs if (path / "final_articles_index.md").exists()]
    if not index_dirs:
        failures.append("No final_articles_index.md found in outputs/YYYY-MM-DD.")

    if failures:
        return CheckResult("Local artifacts", False, failures)
    latest_date = sorted(date_dirs)[-1].name
    return CheckResult(
        "Local artifacts",
        True,
        [
            "workspace/runs/latest_run.json exists.",
            f"Found {len(date_dirs)} dated output directorie(s); latest is outputs/{latest_date}.",
            f"Found final_articles_index.md in {len(index_dirs)} dated directorie(s).",
        ],
    )


def render_report(results: list[CheckResult]) -> str:
    status = "PASS" if all(result.passed for result in results) else "FAIL"
    lines = [
        "# GitHubRadarAgent QA Report",
        "",
        f"- Generated at: {datetime.now().isoformat(timespec='seconds')}",
        f"- Status: **{status}**",
        "",
        "## Checks",
        "",
    ]
    for result in results:
        marker = "PASS" if result.passed else "FAIL"
        lines.append(f"### {result.name}: {marker}")
        for detail in result.details:
            lines.append(f"- {detail}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    results = [
        check_key_files(),
        check_sensitive_info(),
        check_python_compile(),
        check_frontend_package(),
        check_local_artifacts(),
    ]

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render_report(results), encoding="utf-8")

    failed = [result for result in results if not result.passed]
    if failed:
        print("FAIL")
        for result in failed:
            print(f"- {result.name}")
            for detail in result.details:
                print(f"  - {detail}")
        return 1

    print("PASS")
    print(f"QA report: {relative(REPORT_PATH)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
