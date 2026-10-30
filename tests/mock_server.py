"""Local mock of the Verify portal (synthetic data, same JSON shapes as the real API).

Run:  python tests/mock_server.py [port] [n_files]
Credentials: test@example.com / secret
Fault injection: file ids ending in 7 fail once (flaky); the file with id BAD_ID always returns 500.
"""
import json
import random
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

EMAIL, PASSWORD, TOKEN = "test@example.com", "secret", "123|mocktoken"
ORG_UUID = "24e11bd5-0000-0000-0000-b0d45b4c20b0"
OTHER_ORG = "02ae893c-0000-0000-0000-b7c43d7541a6"
PER_PAGE = 50
REMARKS = [
    "Information ok. Address is Ok. Mobile number is ok. Information confirmed by applicant self.",
    "Bank statement verified. Hard copy provided.",
    "Bank statement not  verified.Applicant account seal missing.",
    "Information ok. Given address is mismatched. New address found and verified. New address is House 5, Dhaka.",
    "Applicant does not live in mention address.",
    "Address is ok.\nMobile number is ok.\nConfirmed by Caretaker.\nNo visible holding nameplate of given address.",
    "=HYPERLINK(\"http://evil\") formula-like text that must stay text",
    "Some very unusual remark that matches no rule at all, with a long tail to be truncated properly by the tool.",
    "",
]
TRIP_TYPES = ["HOUSE", "OFFICE", "GUARANTOR_HOUSE", "GUARANTOR_OFFICE", "BANK", "DOCUMENT"]


def make_data(n):
    rnd = random.Random(42)
    files = []
    for i in range(n):
        fid = 300000 + i
        in_scope = i < n  # all belong to Prime
        cons = []
        for k in range(rnd.randint(1, 3)):
            cid = fid * 10 + k
            trips = []
            for _ in range(rnd.randint(1, 4)):
                tid = rnd.randint(400000, 9999999)
                appts = [{
                    "id": rnd.randint(40000, 99999), "task_id": tid,
                    "appointment_time": f"2026-10-{rnd.randint(1, 28):02d} 12:00:00",
                    "appointment_type": rnd.choice(["PHONE_CALL", "VISIT_PLACE"]),
                    "reason": rnd.choice(["Need LOI", "Applicant request to verify later"]),
                    "is_active": rnd.randint(0, 1), "created_at": "2026-10-01 10:00:00", "attachments": [],
                } for _ in range(rnd.choice([0, 0, 1, 3]))]
                t = {
                    "id": tid, "concern_id": cid, "address": f"House {tid}, Road 1, Dhaka", "area": "Gulshan",
                    "exact_address": "Some Place, Dhaka", "is_verified": 1, "assigned_to": "5422",
                    "is_address_exact": rnd.randint(0, 1), "status": rnd.choice([4, 5, 5, 5, 6, 7]),
                    "created_at": "2026-09-28 17:58:22", "latitude": "23.7", "longitude": "90.4",
                    "place_name": rnd.choice(["", "ACME LTD"]), "type": rnd.choice(TRIP_TYPES),
                    "is_for_recpv": 0, "assigned_by": "Tajul Islam",
                    "agent": {"id": 5422, "name": "Tuhin Dewan"}, "appointments": appts or None,
                }
                rem = rnd.choice(REMARKS)
                if rem:
                    t["remarks"] = rem
                    t["start_time"] = "2026-10-07 08:41:43"
                    t["end_time"] = "2026-10-07 08:52:20"
                if rnd.random() < .3:
                    t["comment"] = "TAKE SIGN FROM OFFICE"
                trips.append(t)
            cons.append({"id": cid, "application_id": fid, "name": f"Person {fid}-{k}",
                         "designation": "SENIOR OFFICER", "type": ["APPLICANT", "GUARANTOR", "CO_APPLICANT"][k],
                         "phone": "01700000000", "trips": trips})
        # duplicate a trip id across concerns in one file to test uniqueness
        if i == 3 and len(cons) > 1:
            cons[1]["trips"].append(dict(cons[0]["trips"][0], concern_id=cons[1]["id"]))
        files.append({
            "id": fid, "application_id": f"{rnd.choice(['PL', 'CC'])}-2026{i:012d}",
            "application_type": rnd.choice([1, 2]), "start_date": "2026-09-28 17:58:20",
            "status": rnd.randint(1, 8), "sla": "2026-11-05 14:00:00", "is_verified": 0,
            "station": rnd.choice(["IN_STATION", "OUT_STATION"]), "group_uuid": ORG_UUID,
            "is_download_enabled": 1, "assigned_by": 5468, "issues": [],
            "group": {"id": 40, "uuid": ORG_UUID, "name": "Prime Bank PLC"},
            "concerns": cons, "attachments": [], "ocrs": [],
        })
    return files


STATE = {"files": [], "log": [], "flaky": set(), "lock": threading.Lock(), "bad": None}


def list_item(f):
    return {k: f[k] for k in ("id", "application_id", "is_verified", "status", "start_date", "application_type",
                              "sla", "group_uuid", "assigned_by", "issues", "group")} | {
        "concerns": [{k: v for k, v in c.items() if k != "trips"} for c in f["concerns"]],
        "trips": [t for c in f["concerns"] for t in c["trips"]]}


class Srv(ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def _send(self, code, obj, headers=None):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _auth(self):
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        with STATE["lock"]:
            STATE["log"].append(("GET", p))
        if p == "/api/auth/providers":
            return self._send(200, {"credentials": {}})
        if p == "/api/auth/csrf":
            return self._send(200, {"csrfToken": "abc"}, {"Set-Cookie": "csrf=abc; Path=/"})
        if p == "/api/auth/session":
            if "logged=1" in (self.headers.get("Cookie") or ""):
                return self._send(200, {"user": {"id": 1}, "accessToken": TOKEN})
            return self._send(200, {})
        if not self._auth():
            return self._send(401, {"message": "Unauthenticated."})
        if p == "/api/v2/auth/user":
            return self._send(200, {"data": {"organizations": [
                {"id": 40, "name": "Prime Bank PLC", "uuid": ORG_UUID},
                {"id": 22, "name": "LankaBangla Finance Limited", "uuid": OTHER_ORG}]}})
        if p == "/api/v2/manager/applications":
            assert q.get("org_id[]") == [ORG_UUID], q
            assert sorted(q.get("status[]")) == [str(i) for i in range(1, 9)], q
            page = int(q.get("page", ["1"])[0])
            fl = STATE["files"]
            chunk = fl[(page - 1) * PER_PAGE: page * PER_PAGE]
            last = max(1, -(-len(fl) // PER_PAGE))
            return self._send(200, {"applications": {"current_page": page, "data": [list_item(f) for f in chunk],
                                                      "last_page": last, "per_page": PER_PAGE, "total": len(fl)},
                                    "processes": []})
        if p.startswith("/api/v2/manager/applications/"):
            fid = int(p.rsplit("/", 1)[1])
            if fid == STATE["bad"]:
                return self._send(500, {"message": "boom"})
            if fid % 10 == 7 and fid not in STATE["flaky"]:
                with STATE["lock"]:
                    STATE["flaky"].add(fid)
                return self._send(503, {"message": "try later"})
            for f in STATE["files"]:
                if f["id"] == fid:
                    return self._send(200, {"application": f})
            return self._send(404, {})
        return self._send(404, {"message": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = parse_qs(self.rfile.read(n).decode())
        with STATE["lock"]:
            STATE["log"].append(("POST", u.path))
        if u.path == "/api/auth/callback/credentials":
            ok = body.get("email") == [EMAIL] and body.get("password") == [PASSWORD] and body.get("csrfToken") == ["abc"]
            hdr = {"Set-Cookie": "logged=1; Path=/"} if ok else {}
            return self._send(200, {"url": "http://x/login" + ("" if ok else "?error=CredentialsSignin")}, hdr)
        return self._send(405, {})

    def do_DELETE(self):
        with STATE["lock"]:
            STATE["log"].append(("DELETE", self.path))
        self._send(405, {})


def start(port=0, n=120, bad_index=None):
    STATE["files"] = make_data(n)
    STATE["bad"] = STATE["files"][bad_index]["id"] if bad_index is not None else None
    STATE["log"].clear()
    STATE["flaky"].clear()
    srv = Srv(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    start(port, n, bad_index=5)
    print(f"mock on http://127.0.0.1:{port}  ({n} files)  login test@example.com / secret")
    threading.Event().wait()
