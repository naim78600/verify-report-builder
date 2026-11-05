import email
import sys
from datetime import date
from email import policy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from fake_smtp import FakeSMTP  # noqa: E402

from report_builder import mailer  # noqa: E402
from report_builder.mail_templates import TEMPLATES, MailFacts, render  # noqa: E402
from report_builder.signature import DEFAULT_SIGNATURE, logo_file, signature_html, signature_text  # noqa: E402


@pytest.fixture(autouse=True)
def _tmp_settings(tmp_path, monkeypatch):
    from report_builder import config
    monkeypatch.setattr(config, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mailer, "SENT_LOG", tmp_path / "sent.json")
    monkeypatch.setattr(mailer, "SETTINGS_DIR", tmp_path)


def _xlsx(tmp_path):
    p = tmp_path / "Prime_Bank_Submission_Tracker_2026-11-05_Phase2.xlsx"
    p.write_bytes(b"PK\x03\x04fake-xlsx-bytes")
    return p


def _draft(tmp_path, **kw):
    facts = MailFacts(date(2026, 11, 5), "7pm", False, 14, 16, 6, 9, 5, 2, 0)
    subject, body = render("formal", facts)
    d = mailer.MailDraft(to=["bank.a@example.com", "bank.b@example.com"], cc=["cc@example.com"], subject=subject, body=body,
                         attachments=[str(_xlsx(tmp_path))], signature=dict(DEFAULT_SIGNATURE))
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def test_templates_have_no_tables_and_right_numbers():
    f = MailFacts(date(2026, 11, 5), "3pm", False, 3, 4, 2, 2, 1, 1, 0)
    for tid, _ in TEMPLATES:
        s, b = render(tid, f)
        assert "05" in s and "1st" in s
        assert "|" not in b and "\t" not in b and "<table" not in b.lower()
        assert "3 files" in b
    f0 = MailFacts(date(2026, 11, 5), "7pm", False, 0, 0, 0, 0, 0, 0, 0)
    assert "No file has been submitted" in render("formal", f0)[1]


def test_parse_and_validate_addresses():
    assert mailer.parse_addresses("A@x.com; b@y.com  a@x.com,<c@z.com>") == ["a@x.com", "b@y.com", "c@z.com"]
    assert mailer.invalid_addresses(["a@b", "ok@x.com", "x@localhost"]) == ["a@b"]


def test_message_structure(tmp_path):
    msg = mailer.build_message(_draft(tmp_path), mailer.SmtpSettings())
    parsed = email.message_from_bytes(msg.as_bytes(), policy=policy.default)
    assert parsed["From"].endswith("<verify@barikoi.com>")
    assert parsed["Cc"] == "cc@example.com"
    kinds = [p.get_content_type() for p in parsed.walk()]
    assert "text/plain" in kinds and "text/html" in kinds and "image/png" in kinds
    assert any(p.get_filename() == "Prime_Bank_Submission_Tracker_2026-11-05_Phase2.xlsx" for p in parsed.walk())
    html = parsed.get_body(("html",)).get_content()
    assert "Saikat Francis Gomes" in html and "cid:barikoi_logo" in html and "<table" not in html.lower()
    text = parsed.get_body(("plain",)).get_content()
    assert "Executive-Client Operation" in text and "Phone: +8801321167537" in text and "Barikoi Technologies Limited" in text


def test_send_via_fake_server_and_password_not_saved(tmp_path):
    with FakeSMTP(password="app-pass-123") as srv:
        smtp = mailer.SmtpSettings(host="127.0.0.1", port=srv.port, security="none", username="verify@barikoi.com")
        d = _draft(tmp_path)
        msg = mailer.build_message(d, smtp)
        rcpts = mailer.envelope_recipients(d, smtp)
        mailer.send_message(msg, smtp, "app-pass-123", rcpts)
        assert srv.logins == ["verify@barikoi.com"]
        assert len(srv.messages) == 1
        got = srv.messages[0]
        assert got["from"] == "verify@barikoi.com"
        assert set(got["to"]) == {"bank.a@example.com", "bank.b@example.com", "cc@example.com", "verify@barikoi.com"}
        assert b"Bcc" not in got["data"]
        mailer.save_smtp_settings(smtp)
    from report_builder import config
    assert "app-pass-123" not in config.SETTINGS_FILE.read_text()


def test_wrong_password_and_refused_recipient(tmp_path):
    with FakeSMTP(password="right") as srv:
        smtp = mailer.SmtpSettings(host="127.0.0.1", port=srv.port, security="none")
        d = _draft(tmp_path)
        with pytest.raises(mailer.MailError, match="App Password"):
            mailer.send_message(mailer.build_message(d, smtp), smtp, "wrong", mailer.envelope_recipients(d, smtp))
        assert srv.messages == []
    with FakeSMTP(refuse=["bank.b@example.com"]) as srv:
        smtp = mailer.SmtpSettings(host="127.0.0.1", port=srv.port, security="none")
        d = _draft(tmp_path)
        with pytest.raises(mailer.MailError):
            mailer.send_message(mailer.build_message(d, smtp), smtp, None, ["bank.b@example.com"])


def test_unreachable_server_message(tmp_path):
    smtp = mailer.SmtpSettings(host="127.0.0.1", port=1, security="none", timeout=2)
    d = _draft(tmp_path)
    with pytest.raises(mailer.MailError, match="Could not reach"):
        mailer.send_message(mailer.build_message(d, smtp), smtp, None, ["a@b.com"])


def test_check_draft(tmp_path):
    assert mailer.check_draft(_draft(tmp_path)) == []
    probs = mailer.check_draft(mailer.MailDraft())
    assert len(probs) >= 4
    probs = mailer.check_draft(_draft(tmp_path, to=["bad@@x"]))
    assert any("Invalid" in p for p in probs)


def test_duplicate_guard(tmp_path):
    d = _draft(tmp_path)
    assert mailer.already_sent(date(2026, 11, 5), "7pm") is None
    mailer.log_sent(date(2026, 11, 5), "7pm", d, "x.xlsx")
    assert mailer.already_sent(date(2026, 11, 5), "7pm")["file"] == "x.xlsx"
    assert mailer.already_sent(date(2026, 11, 5), "3pm") is None
    assert mailer.sent_log()[0]["subject"] == d.subject


def test_signature_defaults_and_logo():
    sig = dict(DEFAULT_SIGNATURE)
    assert "Saikat Francis Gomes" in signature_text(sig)
    assert logo_file(sig) is not None and logo_file(sig).stat().st_size > 1000
    assert "cid:barikoi_logo" in signature_html(sig)
    sig["use_logo"] = False
    assert logo_file(sig) is None and "cid:" not in signature_html(sig, with_logo=False)


def test_logo_is_found_inside_a_pyinstaller_bundle(tmp_path, monkeypatch):
    """The packaged app unpacks data files under sys._MEIPASS/<dest>; the build.yml --add-data dest is report_builder/assets."""
    import shutil
    from report_builder import signature
    dest = tmp_path / "report_builder" / "assets"
    dest.mkdir(parents=True)
    shutil.copy(signature.bundled_logo(), dest / "barikoi_logo.png")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert signature.bundled_logo() == dest / "barikoi_logo.png"
