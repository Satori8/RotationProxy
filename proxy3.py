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
        # Load CustomTkinter dynamically to save start-up overhead if running CLI server
        import customtkinter as ctk
        from proxy_core.gui import ProxyGUI

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        gui_app = ProxyGUI(host=args.host, port=args.port, reload=args.reload)

        gui_app.mainloop()
    else:
        import uvicorn

        # Run Foreground Server via Uvicorn
        uvicorn.run(
            "proxy_core.server:app", host=args.host, port=args.port, reload=args.reload
        )
