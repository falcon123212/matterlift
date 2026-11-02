"""In CI every tool is installed (Godot, the glTF/MaterialX/USD validators): a skipped test there
means one went missing, so the run fails instead of passing quietly. Locally, skips stay skips."""
import os


def pytest_sessionfinish(session, exitstatus):
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    skipped = reporter.stats.get("skipped", []) if reporter else []
    if os.environ.get("CI") and skipped and exitstatus == 0:
        reporter.write_line(f"CI: {len(skipped)} test(s) skipped, a required tool is missing", red=True)
        session.exitstatus = 1
