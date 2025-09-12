#!/usr/bin/env python3
import requests, time, sys, os, argparse, zipfile, io, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

API = "https://api.github.com"

def auth_headers(token):
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}

def dispatch_workflow(owner, repo, workflow, ref, token, inputs=None):
    url = f"{API}/repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches"
    body = {"ref": ref}
    if inputs:
        body["inputs"] = inputs
    r = requests.post(url, json=body, headers=auth_headers(token))

    return r.status_code in (204, 201)

def find_recent_run(owner, repo, workflow, after_ts, token, attempts=30, wait=2):
    """Polls workflow runs for the workflow file and returns the run dict created after after_ts."""
    url = f"{API}/repos/{owner}/{repo}/actions/workflows/{workflow}/runs"
    for i in range(attempts):
        r = requests.get(url, params={"per_page": 5}, headers=auth_headers(token))
        r.raise_for_status()
        runs = r.json().get("workflow_runs", [])
        for run in runs:
            created = datetime.fromisoformat(run["created_at"].replace("Z","+00:00"))
            if created >= after_ts - timedelta(seconds=2):
                return run
        time.sleep(wait)
    return None

def wait_run_complete(owner, repo, run_id, token, timeout=1800, poll=5):
    url = f"{API}/repos/{owner}/{repo}/actions/runs/{run_id}"
    t0 = time.time()
    while True:
        r = requests.get(url, headers=auth_headers(token))
        r.raise_for_status()
        run = r.json()
        if run["status"] == "completed":
            return run
        if time.time() - t0 > timeout:
            raise TimeoutError("Waiting for run timed out")
        time.sleep(poll)

def list_artifacts(owner, repo, run_id, token):
    url = f"{API}/repos/{owner}/{repo}/actions/runs/{run_id}/artifacts"
    r = requests.get(url, headers=auth_headers(token))
    r.raise_for_status()
    return r.json().get("artifacts", [])

def download_artifact(owner, repo, artifact_id, token):
    url = f"{API}/repos/{owner}/{repo}/actions/artifacts/{artifact_id}/zip"
    r = requests.get(url, headers=auth_headers(token), stream=True)
    r.raise_for_status()
    return r.content

def parse_junit_from_zip_bytes(zip_bytes):
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    totals = {"tests":0, "failures":0, "errors":0, "skipped":0}
    details = []
    for name in z.namelist():
        if name.endswith('.xml'):
            try:
                data = z.read(name)
                root = ET.fromstring(data)
                if root.tag == 'testsuites':
                    suites = root.findall('testsuite')
                elif root.tag == 'testsuite':
                    suites = [root]
                else:
                    continue

                for ts in suites:
                    t = int(ts.attrib.get('tests',0))
                    f = int(ts.attrib.get('failures',0))
                    e = int(ts.attrib.get('errors',0))
                    s = int(ts.attrib.get('skipped',0))
                    totals["tests"] += t; totals["failures"] += f
                    totals["errors"] += e; totals["skipped"] += s

                    for tc in ts.findall('testcase'):
                        failure = tc.find('failure')
                        if failure is not None:
                            msg = failure.text.strip() if failure.text else "(no message)"
                            details.append(
                                f"❌ {tc.attrib.get('name')} — {msg}"
                            )
            except Exception as exc:
                details.append(f"{name}: parse_error: {exc}")
    return totals, details

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--targets", help="Multiline TARGETS env or file", default=os.environ.get("TARGETS"))
    args = parser.parse_args()
    if not args.targets:
        print("No targets specified", file=sys.stderr); sys.exit(2)
    token = os.environ.get("GH_TOKEN")
    if not token:
        print("GH_TOKEN not set", file=sys.stderr); sys.exit(2)

    lines = [l.strip() for l in args.targets.splitlines() if l.strip()]
    report_lines = []
    overall_failed = False

    for line in lines:
        owner_repo, workflow_file, ref = [p.strip() for p in line.split("|")]
        owner, repo = owner_repo.split("/",1)
        now = datetime.now(timezone.utc)
        report_lines.append(f"## {owner}/{repo} — workflow `{workflow_file}` @ {ref}")
        ok = dispatch_workflow(owner, repo, workflow_file, ref, token)
        report_lines.append(f"- Dispatch request: {'ok' if ok else 'FAILED'}")
        if not ok:
            overall_failed = True
            continue

        run = find_recent_run(owner, repo, workflow_file, now, token)
        if not run:
            report_lines.append("- Could not find triggered run (timed out)")
            overall_failed = True
            continue

        run_id = run["id"]
        run_url = run.get("html_url")
        report_lines.append(f"- Run: {run_url} (id={run_id})")
        try:
            completed = wait_run_complete(owner, repo, run_id, token)
        except TimeoutError as e:
            report_lines.append(f"- Waiting for completion timed out: {e}")
            overall_failed = True
            continue

        conclusion = completed.get("conclusion")
        report_lines.append(f"- Conclusion: {conclusion}")
        if conclusion != "success":
            overall_failed = True

        artifacts = list_artifacts(owner, repo, run_id, token)
        if artifacts:
            report_lines.append(f"- Artifacts found: {len(artifacts)}")
            for art in artifacts:
                report_lines.append(f"  - {art['name']} (id={art['id']})")
                try:
                    zbytes = download_artifact(owner, repo, art['id'], token)
                    totals, details = parse_junit_from_zip_bytes(zbytes)
                    if totals["tests"] > 0:
                        report_lines.append(
                            f"    - parsed junit: tests={totals['tests']} failures={totals['failures']} errors={totals['errors']} skipped={totals['skipped']}"
                        )
                        for d in details:
                            report_lines.append(f"      {d}")
                except Exception as ex:
                    report_lines.append(f"    - error downloading/parsing artifact: {ex}")
        else:
            report_lines.append("- No artifacts. Will try to list jobs")
            jobs_url = f"{API}/repos/{owner}/{repo}/actions/runs/{run_id}/jobs"
            r = requests.get(jobs_url, headers=auth_headers(token))
            if r.ok:
                jobs = r.json().get("jobs",[])
                for j in jobs:
                    report_lines.append(f"  - job {j['name']}: {j.get('conclusion')}")

    md = "# Aggregated orchestrator report\n\n" + "\n".join(report_lines) + "\n"
    with open("aggregated-report.md","w",encoding="utf-8") as f:
        f.write(md)
    print(md)
    if overall_failed:
        print("One or more downstream runs failed -> exit 1")
        sys.exit(1)
    else:
        print("All downstream runs succeeded")
        sys.exit(0)

if __name__ == "__main__":
    main()
