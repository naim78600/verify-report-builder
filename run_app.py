"""Entry point.  GUI:  python run_app.py     Headless:  python run_app.py --cli ..."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))


def send_cli_mail(a, d, outputs) -> int:
    """Send the tracker e-mail from the command line (same engine as the window).  Returns the exit code."""
    import getpass
    import tempfile
    from pathlib import Path

    from report_builder import mailer
    from report_builder import signature as sigmod
    from report_builder.mail_templates import facts_from, render
    from report_builder.reports import has_checklist, strip_checklist

    xlsx = next((p for p in outputs if p.suffix.lower() == ".xlsx"), None)
    rec, smtp = mailer.load_recipients(), mailer.load_smtp_settings()
    to = mailer.parse_addresses(a.to) or rec["to"]
    cc = mailer.parse_addresses(a.cc) if a.cc else rec["cc"]
    bcc = mailer.parse_addresses(a.bcc) if a.bcc else rec["bcc"]
    prev = mailer.already_sent(d.report_date, d.slot)
    if prev and not a.force:
        print(f"Already e-mailed at {prev['sent_at']} (same date + phase). Use --force to send again.")
        return 3
    subject, body = render(a.template, facts_from(d))
    atts = [xlsx]
    if xlsx and has_checklist(xlsx) and not a.keep_checklist:
        atts = [strip_checklist(xlsx, Path(tempfile.mkdtemp(prefix="vrb_mail_")) / xlsx.name)]
    if a.pdf:
        atts += [p for p in outputs if p.suffix.lower() == ".pdf"]
    draft = mailer.MailDraft(to=to, cc=cc, bcc=bcc, subject=subject, body=body, attachments=[str(p) for p in atts],
                             signature=sigmod.load_signature())
    problems = mailer.check_draft(draft)
    if problems:
        print("Cannot send:\n" + "\n".join("  - " + x for x in problems))
        return 2
    pw = os.environ.get("VERIFY_SMTP_PASSWORD") or getpass.getpass(f"SMTP App Password for {smtp.username}: ")
    try:
        mailer.send_message(mailer.build_message(draft, smtp), smtp, pw, mailer.envelope_recipients(draft, smtp))
    except mailer.MailError as exc:
        print("Mail failed:", exc)
        return 1
    mailer.log_sent(d.report_date, d.slot, draft, atts[0].name)
    print(f"Mail sent to {', '.join(to)}" + (f" (cc {', '.join(cc)})" if cc else ""))
    return 0


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
    p.add_argument("--prime", action="store_true", help="Prime Bank tracker / range report (one editable Excel) into --outdir")
    p.add_argument("--after3", action="store_true", help="2nd phase: only the files submitted after 3 PM")
    p.add_argument("--pdf", action="store_true", help="also write the PDF")
    p.add_argument("--send-mail", action="store_true", help="V3: e-mail the Excel (To/Cc/Bcc from the saved settings or --to/--cc/--bcc); "
                                                          "SMTP password from env VERIFY_SMTP_PASSWORD or a prompt")
    p.add_argument("--to", default="")
    p.add_argument("--cc", default="")
    p.add_argument("--bcc", default="")
    p.add_argument("--template", default="formal", choices=["formal", "concise", "executive"])
    p.add_argument("--keep-checklist", action="store_true", help="do not remove the internal Check List sheet from the attachment")
    p.add_argument("--force", action="store_true", help="send even if this date + phase was already e-mailed")
    p.add_argument("--mode", default="tracker", choices=["tracker", "range"])
    p.add_argument("--report-date", default="")
    p.add_argument("--from", dest="dfrom", default="", help="range mode: first date YYYY-MM-DD (default: today minus --days)")
    p.add_argument("--till", default="")
    p.add_argument("--slot", default="", choices=["", "3pm", "7pm"])
    p.add_argument("--outdir", default=".")
    p.add_argument("--bill", default="", help="v6: monthly bill for YYYY-MM (Card + Loan, Excel + PDF) into --outdir")
    p.add_argument("--history", default="", help="v2.2: File History - Excel/CSV/TXT of file numbers (full or last digits) into --outdir")
    p.add_argument("--refresh-index", action="store_true", help="File History: read the whole file list again")
    a = p.parse_args(argv)
    pw = os.environ.get("VERIFY_PASSWORD") or getpass.getpass("Password: ")
    cfg = RunConfig(web=a.web, api=a.api or config.derive_api_url(a.web), server_label=a.web, email=a.email,
                    password=pw, days=a.days, org_name=a.org, workers=a.workers)
    last = [""]
    if a.history:
        from report_builder.file_history import HistoryConfig, collect_history, parse_ids_file
        from report_builder.history_excel import write_history_outputs
        ids = parse_ids_file(a.history)
        print(f"{len(ids)} file number(s) found in {a.history}", flush=True)
        hc = HistoryConfig(web=cfg.web, api=cfg.api, server_label=cfg.server_label, email=a.email, password=pw,
                           org_name=a.org, workers=a.workers, ids=ids, refresh_index=a.refresh_index)
        h = collect_history(hc, lambda s, n, t, m: print(m, flush=True), threading.Event())
        for p_ in write_history_outputs(h, Path(a.outdir)):
            print("Saved", p_)
        print(f"found {len(h.results)} file(s), not found {len(h.not_found)} number(s)")
        return
    if a.bill:
        from datetime import date
        from report_builder.bill_out import write_month_bill
        from report_builder.collect_prime import PrimeConfig, collect_prime
        from report_builder.monthly_bill import build_month_bill, month_window
        try:
            year, month = (int(x) for x in a.bill.split("-"))
            lo, hi = month_window(year, month)
        except ValueError:
            raise SystemExit("--bill needs a month like 2026-09")
        pc = PrimeConfig(web=cfg.web, api=cfg.api, server_label=cfg.server_label, email=a.email, password=pw, days=a.days,
                         org_name=a.org, workers=a.workers, mode="bill", date_from=lo, date_till=hi)
        d = collect_prime(pc, lambda s, n, t, m: print(m, flush=True), threading.Event())
        mb = build_month_bill(d.all_rows, year, month, date.today(), d.files)
        for p_ in write_month_bill(mb, Path(a.outdir), excel=True, pdf=True):
            print("Saved", p_)
        for ft, b_ in mb.bills.items():
            print(f"{ft}: {len(b_.items)} rows, subtotal {b_.subtotal}, penalty {b_.deduction}, grand total {b_.grand_total}")
        st = mb.stats
        print(f"created in the month: {st['rows_in_month']} bill rows = {st['billed']} billed + {st['excluded']} left out"
              f" ({len(mb.review)} to look at - see the Check sheet)")
        return
    if a.prime:
        from datetime import date, datetime, timedelta
        from report_builder.collect_prime import PrimeConfig, collect_prime, slot_for
        from report_builder.reports import write_prime_outputs

        def dt(x, dflt):
            return datetime.strptime(x, "%Y-%m-%d").date() if x else dflt
        today = date.today()
        slot = a.slot or slot_for()
        tracker = a.mode == "tracker"
        pc = PrimeConfig(web=cfg.web, api=cfg.api, server_label=cfg.server_label, email=a.email, password=pw,
                         days=a.days, org_name=a.org, workers=a.workers, mode=a.mode,
                         report_date=dt(a.report_date, today), slot=slot, after3_only=bool(a.after3 and tracker and slot == "7pm"),
                         date_from=None if tracker else dt(a.dfrom, today - timedelta(days=a.days)),
                         date_till=None if tracker else dt(a.till, today))
        d = collect_prime(pc, lambda s, n, t, m: print(m, flush=True), threading.Event())
        outputs = write_prime_outputs(d, Path(a.outdir), excel=True, pdf=a.pdf)
        for p_ in outputs:
            print("Saved", p_)
        if a.send_mail:
            if not tracker:
                raise SystemExit("--send-mail works with the daily tracker (--mode tracker) only.")
            raise SystemExit(send_cli_mail(a, d, outputs))
        ck = (d.dash or {}).get("check")
        if ck:
            print(f"Dashboard Submitted files: {ck['dashboard']}  in this report: {ck['matched']}  other phase's mail: {len(ck.get('other_phase') or [])}"
                  f"  not matched: {len(ck['missing'])}")
            for no, why in ck["missing"]:
                print(f"  not matched: {no} - {why}")
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
