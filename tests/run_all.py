"""Run every test suite in a fresh process and summarise.   python tests/run_all.py"""
import os
import subprocess
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
failed = []
for n in range(2, 9):
    script = here / f"test_phase{n}.py"
    if not script.exists():
        continue
    proc = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True)
    ok = proc.returncode == 0 and "ALL OK" in proc.stdout
    print(f"phase {n}: {'PASS' if ok else 'FAIL'}")
    if not ok:
        failed.append(n)
        print(proc.stdout[-1500:], proc.stderr[-1500:])
sys.exit(1 if failed else 0)
