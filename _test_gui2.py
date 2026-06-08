import sys
import os

print("Step 1: Starting...", flush=True)
sys.stdout.flush()

os.environ["GEMINI_PROXY_PROCESS"] = "gui"

print("Step 2: Importing customtkinter...", flush=True)
import customtkinter as ctk

print(f"Step 3: customtkinter v{ctk.__version__} loaded", flush=True)

print("Step 4: Importing ProxyGUI...", flush=True)
from proxy_core.gui import ProxyGUI

print("Step 5: ProxyGUI imported", flush=True)

print("Step 6: Creating ProxyGUI instance (this may hang)...", flush=True)
sys.stdout.flush()

try:
    gui_app = ProxyGUI(host="127.0.0.1", port=4000, reload=False)
    print("Step 7: ProxyGUI instance created!", flush=True)
except Exception as e:
    import traceback

    print(f"ERROR creating ProxyGUI: {e}", flush=True)
    traceback.print_exc(file=sys.stdout)
    sys.stdout.flush()
    sys.exit(1)

print("Done", flush=True)
