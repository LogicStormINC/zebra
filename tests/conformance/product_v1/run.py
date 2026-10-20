"""Product integration contract gate; fixtures are not deployed-product acceptance."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_TESTS = (
    "tests/conformance/host_v1/test_host_conformance.py",
    "tests/conformance/client_v1/test_client_conformance_suite.py",
    "tests/host_grant_broker/test_current_authority.py",
    "tests/host_grant_broker/test_keys.py",
    "tests/agent_integrations/test_schedule_grant_exchange_generic.py",
    "tests/integration/test_client_effect_suspend_resume.py",
    "tests/agent_integrations/test_coverage_snapshot_v2.py",
    "tests/api/test_coverage_report_http.py",
    "tests/api/test_coverage_report_deadline.py",
    "tests/worker/test_coverage_legacy_identity.py",
    "tests/test_runtime_product_boundary.py",
    "tests/test_compatibility_retirement.py",
    "tests/conformance/product_v1/test_gate.py",
)
POSTGRES_TESTS = (
    "tests/agent_storage/test_postgres_command_wakeup_handoff.py",
    "tests/worker/test_coverage_dispatch.py",
    "tests/api/test_coverage_report_read.py",
)


def counts(path: Path) -> dict[str, int]:
    root = ElementTree.parse(path).getroot()
    cases = list(root.iter("testcase"))
    return {
        "tests": len(cases),
        "skipped": sum(case.find("skipped") is not None for case in cases),
        "failed": sum(
            case.find("failure") is not None or case.find("error") is not None for case in cases
        ),
    }


def complete(
    result: dict[str, int], return_code: int, *, missing_modules: tuple[str, ...] = ()
) -> bool:
    return (
        return_code == 0
        and result["tests"] > 0
        and not result["skipped"]
        and not result["failed"]
        and not missing_modules
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres", action="store_true")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    report = evidence / "junit.xml"
    verdict = evidence / "conformance-result.json"
    legacy = evidence / "result.json"
    if legacy.exists():
        try:
            old = json.loads(legacy.read_text())
        except (ValueError, OSError):
            old = None
        if isinstance(old, dict) and old.get("schema") == "overdoze.product-conformance.v1":
            legacy.rename(evidence / "legacy-conformance-result.json")
    selected = POSTGRES_TESTS if args.postgres else CONTRACT_TESTS
    required = tuple(path.removesuffix(".py").replace("/", ".") for path in selected)
    output = {
        "schema": "overdoze.product-conformance.v1",
        "status": "FAIL",
        "mode": "postgres" if args.postgres else "contracts",
        "boundary": "scratch PostgreSQL with Host/S3/model fixtures"
        if args.postgres
        else "in-process fixtures with real protocol and execution paths",
        "production_acceptance": False,
        "skips_allowed": False,
        "prerequisites_present": not args.postgres
        or bool(os.environ.get("ZEBRA_TEST_POSTGRES_DSN")),
        "pytest_return_code": 1,
        "ignored_pytest_addopts": bool(os.environ.get("PYTEST_ADDOPTS")),
        "required_modules": required,
        "missing_modules": required,
        "tests": 0,
        "skipped": 0,
        "failed": 0,
    }
    # Persist refusal before launch so interruption cannot expose the previous PASS.
    verdict.write_text(json.dumps(output, indent=2) + "\n")
    report.unlink(missing_ok=True)
    result = {"tests": 0, "skipped": 0, "failed": 0}
    return_code = 1
    missing = required
    if output["prerequisites_present"]:
        try:
            return_code = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", f"--junitxml={report}", *selected],
                cwd=ROOT,
                check=False,
                env={key: value for key, value in os.environ.items() if key != "PYTEST_ADDOPTS"},
            ).returncode
            result = counts(report)
            classes = [
                case.get("classname", "") for case in ElementTree.parse(report).iter("testcase")
            ]
            missing = tuple(
                name
                for name in required
                if not any(value == name or value.startswith(name + ".") for value in classes)
            )
        except (OSError, ValueError, ElementTree.ParseError):
            return_code = 1
    passed = complete(result, return_code, missing_modules=missing)
    output.update(
        status="PASS" if passed else "FAIL",
        pytest_return_code=return_code,
        missing_modules=missing,
        **result,
    )
    verdict.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, sort_keys=True))
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
