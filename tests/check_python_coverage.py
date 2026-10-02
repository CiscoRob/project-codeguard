"""Require each top-level src module's own test file to cover at least 95%."""

import subprocess
import sys
import tempfile
from pathlib import Path

from coverage import Coverage

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "src"
TEST_DIR = ROOT / "tests"
MINIMUM_COVERAGE = 95.0


def main() -> int:
    sources = sorted(SOURCE_DIR.glob("*.py"))
    if not sources:
        print("No top-level Python sources found", file=sys.stderr)
        return 1

    failures = []
    with tempfile.TemporaryDirectory(prefix="codeguard-coverage-") as temporary:
        for source in sources:
            test = TEST_DIR / f"test_{source.stem}.py"
            if not test.is_file():
                failures.append(f"{source.name}: missing {test.name}")
                continue

            data_file = Path(temporary) / f".coverage.{source.stem}"
            command = [
                sys.executable,
                "-m",
                "coverage",
                "run",
                "--data-file",
                str(data_file),
                f"--include={source}",
                "-m",
                "unittest",
                "discover",
                "-s",
                str(TEST_DIR),
                "-p",
                test.name,
                "-q",
            ]
            result = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
            if result.returncode:
                print(result.stdout, file=sys.stderr)
                print(result.stderr, file=sys.stderr)
                failures.append(f"{test.name}: tests failed ({result.returncode})")
                continue

            coverage = Coverage(data_file=str(data_file))
            coverage.load()
            _, statements, _, missing, _ = coverage.analysis2(str(source))
            covered = len(statements) - len(missing)
            percent = 100.0 * covered / len(statements) if statements else 100.0
            print(f"{source.name}: {percent:.1f}% ({covered}/{len(statements)}) via {test.name}")
            if percent < MINIMUM_COVERAGE:
                failures.append(
                    f"{source.name}: {percent:.1f}% is below {MINIMUM_COVERAGE:.0f}% "
                    f"(missing lines: {missing})"
                )

    if failures:
        print("\nPython coverage requirements failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"\nEvery top-level src module meets {MINIMUM_COVERAGE:.0f}% coverage.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
