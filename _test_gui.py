import sys

print("Step 1: Starting import test...", flush=True)
sys.stdout.flush()

try:
    import customtkinter as ctk

    print(f"Step 2: customtkinter loaded, version: {ctk.__version__}", flush=True)

    from proxy_core.gui import ProxyGUI

    print("Step 3: ProxyGUI imported successfully", flush=True)
except Exception as e:
    import traceback

    print(f"ERROR: {e}", flush=True)
    traceback.print_exc(file=sys.stdout)
    sys.stdout.flush()
    sys.exit(1)

print("Step 4: All imports done!", flush=True)
