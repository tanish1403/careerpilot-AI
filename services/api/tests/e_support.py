"""Lane E test support: local fixture ATS server + data builders."""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FIELDS = """
<div class="field"><label for="first_name">First Name *</label>
 <input id="first_name" name="job_application[first_name]" type="text" required></div>
<div class="field"><label for="last_name">Last Name *</label>
 <input id="last_name" name="job_application[last_name]" type="text" required></div>
<div class="field"><label for="email">Email *</label>
 <input id="email" name="job_application[email]" type="email" required></div>
<div class="field"><label for="phone">Phone</label>
 <input id="phone" name="job_application[phone]" type="tel"></div>
"""
BUTTON = '<button type="submit" id="submit_app">Submit Application</button>'


def page(body: str, title: str = "Apply") -> str:
    return f"<!doctype html><html><head><title>{title}</title></head><body><h1>{title}</h1>{body}</body></html>"


GREENHOUSE = page(f"""
<form id="application_form" action="/submit" method="post">{FIELDS}
<div class="field"><label for="resume">Resume/CV</label><input id="resume" name="resume" type="file"></div>
<div class="field"><label for="linkedin">LinkedIn Profile</label><input id="linkedin" name="linkedin" type="text"></div>
<div class="field"><label for="why">Why do you want to work here?</label><textarea id="why" name="why"></textarea></div>
<div class="field"><label for="auth">Are you legally authorized to work in the United States?</label>
 <select id="auth" name="auth"><option value="">--</option><option>Yes</option><option>No</option></select></div>
<div class="field"><label for="gender">Gender</label>
 <select id="gender" name="gender"><option value="">--</option><option>Female</option><option>Male</option></select></div>
<div class="field"><input id="consent" name="consent" type="checkbox"><label for="consent">I agree to the privacy policy</label></div>
<input type="text" name="hp" style="position:absolute;left:-9999px" tabindex="-1" aria-hidden="true">
{BUTTON}</form>""", "Acme - Engineer")

CAPTCHA = page(f"""<form id="application_form" action="/submit" method="post">{FIELDS}
<div class="g-recaptcha" data-sitekey="abc"></div>{BUTTON}</form>""", "Captcha job")
LOGIN = page("""<form action="/login" method="post"><label for="u">Username</label><input id="u" name="u">
<label for="p">Password</label><input id="p" name="p" type="password"><button>Sign in</button></form>""",
             "Sign in to continue")
SENSITIVE = page(f"""<form id="application_form" action="/submit" method="post">{FIELDS}
<div class="field"><label for="vis">Will you now or in the future require visa sponsorship?</label><input id="vis" name="vis"></div>
<div class="field"><label for="dis">Do you have a disability?</label><input id="dis" name="dis"></div>
<div class="field"><label for="crim">Have you ever been convicted of a felony?</label><input id="crim" name="crim"></div>
{BUTTON}</form>""", "Sensitive job")
REJECT = page("""<form id="application_form" action="/submit" method="post">
<label for="first_name">First Name</label><input id="first_name" name="fn">
<label for="email">Email</label><input id="email" name="em" oninput="this.value=''">
<button type="submit">Submit Application</button></form>""", "Rejecting job")
AMBIGUOUS = page(f"""<form id="a" action="/submit" method="post">{FIELDS}</form>
<form id="b" action="/submit" method="post"><label for="x">Newsletter name</label><input id="x" name="x">
<label for="y">Newsletter email</label><input id="y" name="y"></form>""", "Ambiguous")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # noqa: ANN002
        pass

    def _send(self, code: int, body: str = "", headers: dict | None = None):
        data = body.encode()
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        self.server.log.append(("GET", self.path))
        routes = {"/greenhouse": GREENHOUSE, "/captcha": CAPTCHA, "/login": LOGIN,
                  "/sensitive": SENSITIVE, "/reject": REJECT, "/ambiguous": AMBIGUOUS}
        if self.path == "/redirect":
            return self._send(302, "", {"Location": f"http://localhost:{self.server.server_port}/greenhouse"})
        if self.path == "/redirect-ok":
            return self._send(302, "", {"Location": "/greenhouse"})
        if self.path in routes:
            return self._send(200, routes[self.path])
        self._send(404, "nope")

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        self.server.log.append(("POST", self.path))
        self._send(200, "SUBMITTED")


class FixtureServer:
    def __init__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.log = []
        self.port = self.httpd.server_port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):  # noqa: ANN002
        self.httpd.shutdown()
        self.httpd.server_close()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    @property
    def posts(self) -> list:
        return [r for r in self.httpd.log if r[0] != "GET"]


# ---- data builders ---------------------------------------------------------------------------
def make_job(db, url="https://boards.greenhouse.io/acme/jobs/1", key="k1", title="Engineer"):
    from careerpilot.db.models import Job
    j = Job(dedupe_key=key, title=title, company_name="Acme", canonical_url=url)
    db.add(j)
    db.flush()
    return j


def make_profile(db, confirmed=True):
    from careerpilot.db.models import CandidateProfile, ProfileFact
    p = CandidateProfile(links={}, preferences={})
    db.add(p)
    db.flush()
    st = "confirmed" if confirmed else "proposed"
    facts = [
        ProfileFact(profile_id=p.id, category="contact", key="contact", status=st,
                    value={"full_name": "Ada Lovelace", "email": "ada@example.com",
                           "phone": "+44 20 7946 0958", "location": "London",
                           "links": {"linkedin": "https://linkedin.com/in/ada"}}),
        ProfileFact(profile_id=p.id, category="experience", key="exp", status=st,
                    value={"company": "Analytical Engines", "title": "Mathematician",
                           "start_date": "2020-01"}),
    ]
    db.add_all(facts)
    db.flush()
    return p, facts


def make_resume(db, profile, job, pdf_path=None):
    from careerpilot.db.models import ResumeVersion
    rv = ResumeVersion(profile_id=profile.id, job_id=job.id, latex_source="x", version_no=1,
                       pdf_path=pdf_path)
    db.add(rv)
    db.flush()
    return rv


def make_app(db, state="Discovered", url="https://boards.greenhouse.io/acme/jobs/1", key="k1"):
    from careerpilot.applications import service as svc
    job = make_job(db, url, key)
    app, _ = svc.create_application(db, job.id, "tester")
    app.state = state
    db.commit()
    return app, job
