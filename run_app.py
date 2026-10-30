"""Entry point.  GUI:  python run_app.py     Headless:  python run_app.py --cli ..."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))


def cli(argv):
    import argparse
    import getpass
    import threading
    from pathlib import Path

    from report_builder import config
    from report_builder.collect import RunConfig, collect
    from report_builder.excel import build_workbook

    p = argparse.ArgumentParser(description="Headless report run (same engine as the window).")
    p.add_argument("--cli", action="store_true")
    p.add_argument("--web", default=config.PRODUCTION["web"])
    p.add_argument("--api", default="")
    p.add_argument("--email", required=True)
    p.add_argument("--days", type=int, default=config.DEFAULT_DAYS)
    p.add_argument("--org", default=config.DEFAULT_ORG)
    p.add_argument("--workers", type=int, default=config.DEFAULT_WORKERS)
    p.add_argument("--out", default="report.xlsx")
    a = p.parse_args(argv)
    pw = os.environ.get("VERIFY_PASSWORD") or getpass.getpass("Password: ")
    cfg = RunConfig(web=a.web, api=a.api or config.derive_api_url(a.web), server_label=a.web, email=a.email,
                    password=pw, days=a.days, org_name=a.org, workers=a.workers)
    last = [""]

    def progress(stage, done, total, msg):
        if msg != last[0]:
            print(msg, flush=True)
            last[0] = msg

    res = collect(cfg, progress, threading.Event())
    path = build_workbook(res, Path(a.out))
    print(f"Saved {path}  files={len(res.files)}/{res.site_total} failed={len(res.failed)}")


if __name__ == "__main__":
    if "--cli" in sys.argv:
        cli(sys.argv[1:])
    else:
        from report_builder.gui import run
        run()
