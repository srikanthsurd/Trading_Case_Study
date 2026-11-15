import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

try:
    subprocess.run(
        [sys.executable, str(ROOT / "src" / "run_research.py"), "--run"],
        cwd=ROOT,
        check=True,
    )
except subprocess.CalledProcessError as exc:
    if exc.returncode == 2:
        print(
            "\nResearch stopped by the data-quality gate. "
            "Review outputs/data_quality.json and outputs/data_quality.csv, "
            "correct the source data, and rerun.",
            file=sys.stderr,
        )
        sys.exit(2)
    raise

subprocess.run(
    [sys.executable, str(ROOT / "src" / "build_report.py")],
    cwd=ROOT,
    check=True,
)
print("Research workflow adnd PDF report is placed in outputs/.")
