import argparse
import os
import subprocess
import sys
from pathlib import Path

from environment import load_environment

parser = argparse.ArgumentParser()
parser.add_argument("--stack", default="WebHealth-beta")
args = parser.parse_args()
result = subprocess.run([sys.executable, "-m", "pytest", "-m", "integration", "--run-live",
                         "--junitxml=test-results/live.xml"], cwd=Path(__file__).resolve().parents[1],
                        env={**os.environ, **load_environment(args.stack)}, check=False)
raise SystemExit(result.returncode)
