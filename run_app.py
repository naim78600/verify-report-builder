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
    p.add_argument("--prime", action="store_true", help="v2: Prime Bank report (Excel+PDF+email page) into --outdir")
    p.add_argument("--mode", default="tracker", choices=["tracker", "range"])
    p.add_argument("--report-date", default="")
    p.add_argument("--from", dest="dfrom", default="", help="range mode: first date YYYY-MM-DD (default: today minus --days)")
    p.add_argument("--till", default="")
    p.add_argument("--slot", default="", choices=["", "3pm", "7pm"])
    p.add_argument("--outdir", default=".")
    a = p.parse_args(argv)
    pw = os.environ.get("VERIFY_PASSWORD") or getpass.getpass("Password: ")
    cfg = RunConfig(web=a.web, api=a.api or config.derive_api_url(a.web), server_label=a.web, email=a.email,
                    password=pw, days=a.days, org_name=a.org, workers=a.workers)
    last = [""]
    if a.prime:
        from datetime import date, datetime, timedelta
        from report_builder.collect_prime import PrimeConfig, collect_prime, slot_for
        from report_builder.reports import write_prime_outputs

        def dt(x, dflt):
            return datetime.strptime(x, "%Y-%m-%d").date() if x else dflt
        today = date.today()
        pc = PrimeConfig(web=cfg.web, api=cfg.api, server_label=cfg.server_label, email=a.email, password=pw,
                         days=a.days, org_name=a.org, workers=a.workers, mode=a.mode,
                         report_date=dt(a.report_date, today), slot=a.slot or slot_for(),
                         date_from=dt(a.dfrom, today - timedelta(days=a.days)), date_till=dt(a.till, today))
        d = collect_prime(pc, lambda s, n, t, m: print(m, flush=True), threading.Event())
        for p_ in write_prime_outputs(d, Path(a.outdir), email=True):
            print("Saved", p_)
        return

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
