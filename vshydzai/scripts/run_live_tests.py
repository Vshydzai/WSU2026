import argparse
import os
import subprocess
import sys
from pathlib import Path

from environment import load_environment


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run deployed AWS tests and preserve one JUnit report per environment")
    parser.add_argument("--stack", choices=("WebHealth-beta", "WebHealth-gamma", "WebHealth-prod"), default="WebHealth-beta")
    args = parser.parse_args(argv)
    result = subprocess.run([sys.executable, "-m", "pytest", "-m", "integration", "--run-live",
                             "-o", "junit_family=legacy", f"--junitxml=test-results/live-{args.stack}.xml"],
                            cwd=Path(__file__).resolve().parents[1],
                            env={**os.environ, **load_environment(args.stack)}, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
