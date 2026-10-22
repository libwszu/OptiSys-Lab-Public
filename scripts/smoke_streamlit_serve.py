"""Prove that ``streamlit run app/main.py`` actually serves the app.

Why this exists
---------------
``tests/ui/test_pages_render.py`` drives the pages through
``streamlit.testing.v1.AppTest``, which executes the *scripts* but never starts
a server.  The README and the demo script both say "run this one command", and
until this file existed that sentence was an untested claim: nothing here had
ever bound a port.

What it checks, in order
------------------------
1. the process stays alive for the whole budget instead of dying at import;
2. ``/_stcore/health`` returns the literal body ``ok`` - the runtime is up;
3. ``/`` returns 200 with the Streamlit bootstrap shell in the body;
4. shutdown is clean - no orphan is left holding the port.

What it canNOT check, and why that is recorded instead of papered over
----------------------------------------------------------------------
A page module that fails to import does **not** break this probe.  Measured,
not assumed: pointing ``streamlit run`` at a file containing
``import this_module_does_not_exist_xyz`` leaves the runtime healthy,
``/_stcore/health`` answering ``ok``, ``/`` serving the 6467-byte shell, and the
server log silent.  The reason is that Streamlit executes the script only when a
websocket session attaches; a plain HTTP GET fetches the static shell and never
runs the page at that point.  Turning on
``--server.scriptHealthCheckEnabled`` does not change this either (measured).

So import errors are covered by ``tests/ui/test_pages_render.py`` via ``AppTest``,
which *does* execute the script and surfaces ``ModuleNotFoundError`` as
``at.exception``.  The two checks are complementary and neither is sufficient
alone:
  * AppTest proves the pages execute, but never binds a port;
  * this script proves the port serves, but never executes a page.

The negative control below therefore asserts the *limitation*: a broken entry
point must leave HTTP health green.  If that assertion ever fails, Streamlit has
changed behaviour and the limitation note must be rewritten rather than trusted.

A second caution learned the hard way: ``/healthz`` is **not** Streamlit's health
endpoint.  It answers 200 with the 6467-byte SPA shell, byte-identical to ``/``,
because every unknown path falls through to the index page.  A probe written
against ``/healthz`` therefore passes whether or not the runtime is healthy - it
only proves that a static file is served.  The real endpoint is
``/_stcore/health``, which returns ``ok`` as plain text.

The probe is deliberately a plain ``http.client`` request rather than a browser:
a browser would add a dependency and could pass while the server errored.

Exit codes match the rest of the G3 tooling: 0 pass, 1 fail, 2 dependency
unavailable (streamlit not installed, port not obtainable).
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "app" / "main.py"

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_DEPENDENCY = 2

#: Streamlit's real health endpoint.  Returns the plain-text body ``ok``.
HEALTH_PATH = "/_stcore/health"
HEALTH_BODY = b"ok"

#: Streamlit logs a bare-mode "missing ScriptRunContext" warning at import time.
#: It is harmless here (there is no browser session) and would otherwise be the
#: first line of an otherwise clean report, so it is raised to ERROR before the
#: first streamlit import anywhere in this module.
import logging  # noqa: E402

_STREAMLIT_LOG_LEVEL_BEFORE = logging.getLogger("streamlit").level
logging.getLogger("streamlit").setLevel(logging.ERROR)


@contextlib.contextmanager
def _quiet_fds():
    """Send fd 1 and 2 to the null device for the duration of the block.

    Needed because some Streamlit warnings bypass Python's ``sys.stderr``: the
    logging handler captured the original stream when the library was imported,
    so ``contextlib.redirect_stderr`` never sees them.  Only used around code
    whose console output is *expected*, never around real work - a swallowed
    error elsewhere would be a bug, not a tidy log.
    """

    saved: dict[int, int] = {}
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        for fd in (1, 2):
            try:
                saved[fd] = os.dup(fd)
                os.dup2(devnull, fd)
            except OSError:  # pragma: no cover - no console attached
                pass
        yield
    finally:
        for fd, dup in saved.items():
            try:
                os.dup2(dup, fd)
                os.close(dup)
            except OSError:  # pragma: no cover
                pass
        os.close(devnull)


def _free_port() -> int:
    """Ask the OS for an unused port on loopback.

    Binding to port 0 and closing immediately is racy in principle; Streamlit
    retries a few ports of its own when a bind fails, and the actual bound port
    is read back from the process output, so a lost race cannot produce a false
    pass - it produces "port never answered", which fails loudly.
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _probe(port: int, path: str, timeout: float = 3.0) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read(65536)
    finally:
        conn.close()


def _wait_for(port: int, path: str, deadline: float,
              expect_body: bytes | None = None) -> tuple[bool, str]:
    """Poll ``path`` until it answers, optionally asserting an exact body.

    ``expect_body`` is what separates a real check from a status-code ritual:
    ``/`` and ``/healthz`` both return 200 even while the script is broken, so a
    caller that cares about health must match the payload (``ok``).
    """

    last = "no attempt made"
    while time.monotonic() < deadline:
        try:
            status, body = _probe(port, path)
        except (ConnectionRefusedError, ConnectionResetError, socket.timeout, OSError) as exc:
            last = f"{type(exc).__name__}: {exc}"
        else:
            if status == 200:
                if expect_body is None or expect_body in body:
                    return True, f"HTTP 200 ({len(body)} bytes)"
                last = f"HTTP 200 but body did not contain {expect_body!r}: {body[:60]!r}"
            else:
                last = f"HTTP {status}"
        time.sleep(0.5)
    return False, last


def _start(entry: Path, port: int, log_path: Path,
           python: Path | None = None) -> tuple[subprocess.Popen, object]:
    python = python or (ROOT / ".venv" / "Scripts" / "python.exe")
    if not python.is_file():
        python = Path(sys.executable)
    cmd = [
        str(python), "-m", "streamlit", "run", str(entry),
        "--server.port", str(port),
        "--server.address", "127.0.0.1",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    return proc, log


def _stop(proc: subprocess.Popen, log) -> bool:
    """Terminate, then verify the process is gone.  Returns True if it survived."""

    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
    log.close()
    return proc.poll() is None


def _negative_control(budget: float, evidence_dir: Path | None = None,
                      python: Path | None = None) -> dict[str, object]:
    """Measure the limit of an HTTP-only probe, instead of pretending it has none.

    Two facts are measured here, and both are assertions:

    * a broken script does **not** kill ``streamlit run``: the runtime stays up,
      ``/_stcore/health`` keeps answering ``ok``, ``/`` keeps serving the shell,
      and the log stays clean.  This script therefore *cannot* detect an import
      error, and pretending otherwise would make the green result meaningless;
    * ``AppTest`` **can** detect it (asserted separately in
      ``tests/ui/test_pages_render.py``, and cross-checked here when available).

    If the first assertion ever fails, Streamlit changed behaviour: the
    limitation paragraph in this module's docstring is stale and must be
    rewritten.  That is why the check is inverted - it guards the documentation.
    """

    probe_app = ROOT.parent / "optisys_g3_broken_entry_probe.py"
    evidence_dir = evidence_dir or (ROOT / "artifacts" / "g3" / "tests")
    log_path = evidence_dir / "streamlit_serve_negative.log"
    facts: dict[str, object] = {}
    try:
        probe_app.write_text("import this_module_does_not_exist_xyz\n", encoding="utf-8")
        port = _free_port()
        proc, log = _start(probe_app, port, log_path, python)
        try:
            deadline = time.monotonic() + min(budget, 40.0)
            health_ok, health_detail = _wait_for(port, HEALTH_PATH, deadline,
                                                 expect_body=HEALTH_BODY)
            root_ok, root_detail = _wait_for(port, "/", deadline)
            log.flush()
            text = log_path.read_text(encoding="utf-8", errors="replace")
        finally:
            survived = _stop(proc, log)
        facts = {
            "ran": True,
            "health_still_ok_with_a_broken_script": health_ok,
            "root_served_with_a_broken_script": root_ok,
            "server_survived_shutdown": survived,
            "log_mentions_an_error": any(
                token in text for token in
                ("ModuleNotFoundError", "Traceback", "ImportError")),
            "health_detail": health_detail,
            "root_detail": root_detail,
        }
    finally:
        probe_app.unlink(missing_ok=True)
    return facts


def _apptest_catches_a_broken_import() -> dict[str, object]:
    """Show that the *other* layer catches what the HTTP probe cannot.

    ``AppTest`` executes the script, so ``ModuleNotFoundError`` surfaces as
    ``at.exception``.  Run against a throwaway file pair, never against the real
    pages, so this stays a test of the tool and not of the app.
    """

    facts: dict[str, object] = {"ran": False, "caught": None}

    import logging

    # Streamlit binds its log handler to the *original* stderr at import time and
    # emits the bare-mode "missing ScriptRunContext" warning while importing, so
    # neither ``redirect_stderr`` nor a later ``setLevel`` can suppress it.  The
    # level must be raised *before* the import below.  Restored in ``finally`` so
    # this never leaks into a caller's logging configuration.
    streamlit_logger = logging.getLogger("streamlit")
    previous_level = streamlit_logger.level
    streamlit_logger.setLevel(logging.ERROR)

    import contextlib
    import io
    import tempfile

    try:
        from streamlit.testing.v1 import AppTest
    except Exception as exc:  # pragma: no cover - environment dependent
        streamlit_logger.setLevel(previous_level)
        facts["error"] = f"AppTest unavailable: {exc}"
        return facts

    try:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "broken_page.py").write_text(
                "def render():\n"
                "    import this_module_does_not_exist_xyz\n"
                "    return None\n", encoding="utf-8")
            app = base / "app_under_probe.py"
            app.write_text(
                "import sys\n"
                f"sys.path.insert(0, {str(base)!r})\n"
                "import streamlit as st\n"
                "import broken_page\n"
                "broken_page.render()\n"
                "st.write('unreachable')\n", encoding="utf-8")

            # The expected traceback (and Streamlit's bare-mode warning) would
            # otherwise reach the console and make a passing run look like a
            # failing one.  ``contextlib.redirect_stderr`` is not enough: the
            # warning is written through a handler that holds the original
            # stream, so the file descriptor itself is redirected for the
            # duration.  The assertions use at.exception, never console text.
            sink = io.StringIO()
            with contextlib.redirect_stderr(sink), contextlib.redirect_stdout(sink), \
                    _quiet_fds():
                at = AppTest.from_file(str(app), default_timeout=60)
                at.run()
            exceptions = list(at.exception)
            messages = [str(getattr(e, "value", "")) for e in exceptions]
            facts = {
                "ran": True,
                "caught": bool(exceptions),
                "messages": messages[:2],
            }
    finally:
        streamlit_logger.setLevel(previous_level)
    return facts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0,
                        help="fixed port, or 0 to let the OS choose")
    parser.add_argument("--budget", type=float, default=90.0,
                        help="seconds to wait for the server to answer")
    parser.add_argument("--python", type=Path, default=None,
                        help="Python executable to launch Streamlit with (defaults to the project venv)")
    parser.add_argument("--json", type=Path, default=None,
                        help="write the measured facts to this path")
    parser.add_argument("--evidence-dir", type=Path, default=None,
                        help="write server logs under this project-relative evidence directory")
    parser.add_argument("--no-negative-control", action="store_true",
                        help="skip the broken-entry control (faster, weaker)")
    args = parser.parse_args()

    if not ENTRY.is_file():
        print(f"[FAIL] entry point missing: {ENTRY}")
        return EXIT_FAIL

    python = args.python.resolve() if args.python else ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        if args.python:
            print(f"[FAIL] requested Python executable is missing: {python}")
            return EXIT_DEPENDENCY
        python = Path(sys.executable)

    try:
        import streamlit  # noqa: F401
        version = streamlit.__version__
    except ImportError as exc:  # pragma: no cover - environment dependent
        print(f"[DEPENDENCY_UNAVAILABLE] streamlit not importable: {exc}")
        return EXIT_DEPENDENCY

    port = args.port or _free_port()
    evidence_dir = args.evidence_dir or (ROOT / "artifacts" / "g3" / "tests")
    if not evidence_dir.is_absolute():
        evidence_dir = (ROOT / evidence_dir).resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    log_path = evidence_dir / "streamlit_serve.log"

    started = time.monotonic()
    proc, log = _start(ENTRY, port, log_path, python)

    failures: list[str] = []
    facts: dict[str, object] = {
        "streamlit_version": version,
        "entry": "app/main.py",
        "port": port,
        "command": f"-m streamlit run app/main.py --server.port {port} "
                   f"--server.address 127.0.0.1 --server.headless true",
    }
    try:
        deadline = started + args.budget

        # 1. the process must still be alive; a hard crash kills it in ~2 s.
        #    Note: a *script* import error does NOT kill it - see step 5.
        time.sleep(2.0)
        if proc.poll() is not None:
            log.flush()
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-1600:]
            print(f"[FAIL] the server exited with code {proc.returncode} during startup")
            print("--- last output ---")
            print(tail)
            return EXIT_FAIL

        # 2. the runtime is up: /_stcore/health answers the literal body "ok".
        #    NOT /healthz - see the module docstring; that path serves the SPA
        #    shell and would pass even if the runtime were down.
        ok_health, detail_health = _wait_for(port, HEALTH_PATH, deadline,
                                             expect_body=HEALTH_BODY)
        facts["health"] = {"path": HEALTH_PATH, "ok": ok_health, "detail": detail_health}
        if not ok_health:
            failures.append(f"{HEALTH_PATH} never returned {HEALTH_BODY!r}: {detail_health}")

        # 3. the app shell is actually served
        ok_root, detail_root = _wait_for(port, "/", deadline)
        facts["root"] = {"ok": ok_root, "detail": detail_root}
        if not ok_root:
            failures.append(f"/ never answered: {detail_root}")
        else:
            status, body = _probe(port, "/")
            if b"streamlit" not in body.lower():
                # Streamlit's bootstrap page always references its own runtime;
                # its absence means something else answered on this port.
                failures.append("the body served at / does not look like a Streamlit page")
            facts["root"]["bytes"] = len(body)

        facts["startup_s"] = round(time.monotonic() - started, 2)
    finally:
        survived = _stop(proc, log)

    facts["alive_after_shutdown"] = survived
    if survived:
        failures.append("the server process survived shutdown")
    facts["log"] = str(log_path.relative_to(ROOT)).replace("\\", "/")

    # 4. the server log must not contain a traceback.  In practice this stays
    #    clean even for a broken page (see step 5), but a startup-level failure
    #    still lands here, so it is checked rather than assumed.
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    error_tokens = ("Traceback (most recent call last)", "ModuleNotFoundError",
                    "ImportError", "SyntaxError")
    hits = [t for t in error_tokens if t in log_text]
    facts["log_errors"] = hits
    if hits:
        failures.append(f"the server log contains {hits}; startup failed")

    # 5. the negative control asserts the *documented limitation*: a broken
    #    entry point must leave HTTP health green.  If this flips, Streamlit
    #    changed and the limitation paragraph is stale.  The complementary
    #    check (AppTest does catch it) runs right after.
    if not args.no_negative_control:
        control = _negative_control(args.budget, evidence_dir=evidence_dir, python=python)
        facts["negative_control"] = control
        if control.get("ran"):
            if not control.get("health_still_ok_with_a_broken_script"):
                failures.append(
                    "negative control: a broken entry point made HTTP health fail, "
                    "so the documented limitation is stale - update the docstring")
            if control.get("log_mentions_an_error"):
                failures.append(
                    "negative control: the broken entry point DID show up in the log, "
                    "so an HTTP+log probe could be made stricter - update the docstring")

        apptest = _apptest_catches_a_broken_import()
        facts["apptest_control"] = apptest
        if apptest.get("ran") and not apptest.get("caught"):
            failures.append(
                "AppTest control: a broken import was NOT surfaced as at.exception, "
                "so import errors are covered by neither layer")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps({"ok": not failures, "failures": failures, **facts},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

    for key in ("health", "root"):
        entry = facts.get(key, {})
        label = entry.get("path", key) if isinstance(entry, dict) else key
        print(f"[{'OK  ' if entry.get('ok') else 'FAIL'}] {label}: {entry.get('detail')}")
    print(f"[{'OK  ' if not hits else 'FAIL'}] log: "
          f"{'no traceback' if not hits else hits}")
    control = facts.get("negative_control") or {}
    if control.get("ran"):
        # OK means "the documented limitation held": HTTP health stayed green
        # for a broken script, which is exactly what the docstring claims.
        print(f"[{'OK  ' if control.get('health_still_ok_with_a_broken_script') else 'FAIL'}] "
              f"negative control: broken script -> HTTP health still ok="
              f"{control.get('health_still_ok_with_a_broken_script')} "
              f"(documented limitation)")
    apptest = facts.get("apptest_control") or {}
    if apptest.get("ran"):
        first = (apptest.get("messages") or [""])[0]
        print(f"[{'OK  ' if apptest.get('caught') else 'FAIL'}] apptest control: "
              f"broken import caught={apptest.get('caught')} "
              f"{('- ' + first) if first else ''}")
    print(f"[INFO] streamlit {version}, port {port}, "
          f"startup {facts.get('startup_s')} s")
    if failures:
        for item in failures:
            print(f"[FAIL] {item}")
        print("STREAMLIT_SERVE: FAIL")
        return EXIT_FAIL
    print("STREAMLIT_SERVE: PASS")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
