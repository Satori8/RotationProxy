import os
import sys
import argparse

# Force UTF-8 stream encoding on Windows to prevent charmap codec errors with emojis
if sys.platform.startswith("win"):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="ignore")
        except Exception:
            pass

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Resilient Gemini Proxy Server")
    parser.add_argument("--gui", action="store_true", help="Launch with GUI interface")
    parser.add_argument("--host", default="127.0.0.1", help="Host address to bind to")
    parser.add_argument("--port", type=int, default=4000, help="Port to listen on")
    parser.add_argument(
        "--reload", action="store_true", help="Enable auto-reload for development"
    )

    args = parser.parse_args()

    if args.gui:
        import os
        import traceback

        os.environ["GEMINI_PROXY_PROCESS"] = "gui"
        # Load CustomTkinter dynamically to save start-up overhead if running CLI server
        try:
            import customtkinter as ctk
            from proxy_core.gui import ProxyGUI

            ctk.set_appearance_mode("Dark")
            ctk.set_default_color_theme("blue")

            gui_app = ProxyGUI(host=args.host, port=args.port, reload=args.reload)
            gui_app.mainloop()
        except Exception:
            tb = traceback.format_exc()
            print("[FATAL] GUI initialization failed:", file=sys.stderr)
            print(tb, file=sys.stderr)
            crash_log = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "gui_crash.log"
            )
            try:
                with open(crash_log, "w", encoding="utf-8") as f:
                    f.write("GUI CRASH REPORT\n")
                    f.write("================\n")
                    f.write(f"Python: {sys.version}\n")
                    f.write(f"Platform: {sys.platform}\n")
                    f.write(f"Args: {args}\n\n")
                    f.write(tb)
                print(f"[FATAL] Crash report written to {crash_log}", file=sys.stderr)
            except Exception:
                pass
            sys.exit(1)
    else:
        import os

        os.environ["GEMINI_PROXY_PROCESS"] = "server"
        import uvicorn

        # Run Foreground Server via Uvicorn
        uvicorn.run(
            "proxy_core.server:app", host=args.host, port=args.port, reload=args.reload
        )
