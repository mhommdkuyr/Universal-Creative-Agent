"""Smoke test meant to run inside a connected Colab runtime.
The Actions workflow starts this test automatically whenever a task file changes.
"""
import os
import platform
import subprocess
import sys

print("تم الاتصال بـ Google Colab وتنفيذ المهمة عبر GitHub Actions بنجاح!")
print("Platform:", platform.platform())
print("Python:", sys.version.replace("\n", " "))
print("CPU cores:", os.cpu_count())

try:
    gpu = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=15, check=False)
    print("nvidia-smi exit code:", gpu.returncode)
    print(gpu.stdout.strip() or gpu.stderr.strip() or "No GPU information returned.")
except FileNotFoundError:
    print("nvidia-smi is unavailable: this runtime may not have an NVIDIA GPU.")
except subprocess.TimeoutExpired:
    print("nvidia-smi timed out.")
