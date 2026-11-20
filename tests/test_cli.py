"""Headless run: report + e-mail through the local fake SMTP server (nothing leaves the machine)."""
import email
import sys
from email import policy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
import mock_server  # noqa: E402
from fake_smtp import FakeSMTP  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

import run_app  # noqa: E402
from report_builder import config, mailer  # noqa: E402


@pytest.fixture(autouse=True)
def _tmp_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_DIR", tmp_path / "cfg")
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "cfg" / "settings.json")
    monkeypatch.setattr(mailer, "SENT_LOG", tmp_path / "cfg" / "sent.json")
    monkeypatch.setattr(mailer, "SETTINGS_DIR", tmp_path / "cfg")
    monkeypatch.setenv("VERIFY_PASSWORD", "secret")
    monkeypatch.setenv("VERIFY_SMTP_PASSWORD", "app-pass")


def _args(base, out, extra=()):
    return ["--cli", "--web", base, "--api", base, "--email", "test@example.com", "--prime", "--mode", "tracker",
            "--report-date", "2026-11-02", "--slot", "7pm", "--outdir", str(out), *extra]


def test_cli_report_and_mail(tmp_path, capsys):
    srv = mock_server.start_scenario(0)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with FakeSMTP(password="app-pass") as smtp:
            mailer.save_smtp_settings(mailer.SmtpSettings(host="127.0.0.1", port=smtp.port, security="none"))
            with pytest.raises(SystemExit) as ex:
                run_app.cli(_args(base, tmp_path / "out", ["--send-mail", "--to", "a@example.com;b@example.com", "--template", "concise"]))
            assert ex.value.code == 0
            assert len(smtp.messages) == 1 and set(smtp.messages[0]["to"]) == {"a@example.com", "b@example.com", "verify@barikoi.com"}
            msg = email.message_from_bytes(smtp.messages[0]["data"], policy=policy.default)
            assert msg["Subject"].startswith("Verification Submission Tracker")
            att = next(p for p in msg.walk() if (p.get_filename() or "").endswith(".xlsx"))
            (tmp_path / "got.xlsx").write_bytes(att.get_payload(decode=True))
            assert "Check List" not in load_workbook(tmp_path / "got.xlsx").sheetnames            # stripped by default
            assert "Check List" in load_workbook(tmp_path / "out" / "Prime_Bank_Submission_Tracker_2026-11-02_Phase2.xlsx").sheetnames
            # the same date + phase is not sent twice by accident
            with pytest.raises(SystemExit) as ex2:
                run_app.cli(_args(base, tmp_path / "out2", ["--send-mail", "--to", "a@example.com"]))
            assert ex2.value.code == 3 and len(smtp.messages) == 1
            with pytest.raises(SystemExit) as ex3:
                run_app.cli(_args(base, tmp_path / "out3", ["--send-mail", "--to", "a@example.com", "--force", "--keep-checklist"]))
            assert ex3.value.code == 0 and len(smtp.messages) == 2
    finally:
        srv.shutdown()
    assert "Saved" in capsys.readouterr().out


def test_cli_report_only_has_no_mail(tmp_path):
    srv = mock_server.start_scenario(0)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        run_app.cli(_args(base, tmp_path / "out", ["--pdf"]))
    finally:
        srv.shutdown()
    assert sorted(p.suffix for p in (tmp_path / "out").iterdir()) == [".pdf", ".xlsx"]
    assert not (tmp_path / "cfg" / "sent.json").exists()


def test_cli_monthly_bill(tmp_path, capsys):
    """v6: --bill YYYY-MM writes the Card and the Loan bill (Excel + PDF) with the same engine as the window."""
    srv = mock_server.start_scenario(0)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    common = ["--cli", "--web", base, "--api", base, "--email", "test@example.com", "--outdir", str(tmp_path)]
    try:
        run_app.cli(common + ["--bill", "2026-10"])
        out = capsys.readouterr().out
        assert "Card: 4 rows, subtotal 1020" in out and "Loan: 6 rows, subtotal 1860" in out and "10 billed + 0 left out" in out
        assert sorted(p.name for p in tmp_path.glob("Prime_Bank_PLC_*")) == [
            "Prime_Bank_PLC_Card_Invoice_October_2026.pdf", "Prime_Bank_PLC_Card_Invoice_October_2026.xlsx",
            "Prime_Bank_PLC_Card_Mushak6.3_October_2026.pdf",
            "Prime_Bank_PLC_Loan_Invoice_October_2026.pdf", "Prime_Bank_PLC_Loan_Invoice_October_2026.xlsx",
            "Prime_Bank_PLC_Loan_Mushak6.3_October_2026.pdf"]                 # V15: + Mushak-6.3
        with pytest.raises(SystemExit):
            run_app.cli(common + ["--bill", "2026-13"])
    finally:
        srv.shutdown()
