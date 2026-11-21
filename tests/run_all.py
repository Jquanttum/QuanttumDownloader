"""Run every test suite in a fresh process and summarise.   python tests/run_all.py"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

here = Path(__file__).resolve().parent

scripts = [here / f"test_phase{n}.py" for n in range(2, 10)] + [here / "test_phase9_ui.py"]
failed = []
for script in scripts:
    if not script.exists():
        continue
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QUANTTUM_HOME": tempfile.mkdtemp(prefix="qd_home_")}
    proc = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=600)
    ok = proc.returncode == 0 and "ALL OK" in proc.stdout
    print(f"{script.stem}: {'PASS' if ok else 'FAIL'}")
    if not ok:
        failed.append(script.stem)
        print(proc.stdout[-1500:], proc.stderr[-1500:])
sys.exit(1 if failed else 0)
