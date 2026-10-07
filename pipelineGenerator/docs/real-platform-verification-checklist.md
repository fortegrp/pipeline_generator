# Real-Platform Verification Checklist

Everything `pipeline-generator` produces is covered by automated tests, but
those tests run the generated scripts against **stub** `docker`, `wlrun`,
`curl` and `jq`. The items below can only be confirmed against a live
BlazeMeter account, a real LoadRunner Windows agent, and real CI/CD
platforms. Work top to bottom; each check says what to run and what a pass
looks like. Record results in the table at the end.

**Before you start:** generate the setup you're verifying from its example
(or your own config), and commit the generated folder — including
`scripts/.gitattributes` — into a scratch repository on the target platform.

```bash
pipeline-generator generate --config examples/<cicd>-<tool>/customer.yaml --output-dir generated
```

---

## 1. BlazeMeter API (≈20 min, needs an API key with access to one test)

Run these from any machine with `curl` and `jq`, before involving CI. They
are exactly the calls `scripts/run-blazemeter.sh` makes.

```bash
export BLAZEMETER_API_KEY_ID=... BLAZEMETER_API_KEY_SECRET=...
BASE=https://a.blazemeter.com  WS=<workspace id>  PROJ=<project id>  TEST=<test id>
AUTH="$BLAZEMETER_API_KEY_ID:$BLAZEMETER_API_KEY_SECRET"
```

- [ ] **1.1 Project lookup** — `curl -s -o /dev/null -w '%{http_code}\n' -u "$AUTH" "$BASE/api/v4/projects/$PROJ?workspaceId=$WS"`
  Pass: `200`. (Used by `verify_project_exists`.)
- [ ] **1.2 Test lookup** — `curl -s -o /dev/null -w '%{http_code}\n' -u "$AUTH" "$BASE/api/v4/tests/$TEST"`
  Pass: `200`. (Used by `verify_scenario_exists`.)
- [ ] **1.3 Load-profile override** — note the test's current load settings in the BlazeMeter UI first, then:
  ```bash
  curl -sf -u "$AUTH" -X PATCH -H 'Content-Type: application/json' \
    -d '{"overrideExecutions": [{"concurrency": 5, "rampUp": "60s", "holdFor": "2m", "throughput": 3}]}' \
    "$BASE/api/v4/tests/$TEST" | jq .
  ```
  Pass: HTTP 2xx, and the test's settings in the UI now show 5 users, 60 s ramp-up, 2 min hold, 3 req/s.
  Also check: does the PATCH **replace** the whole `overrideExecutions` array (repeat it without
  `"throughput"` — is the cap removed)? Does it need a `locations` field on your account?
  If any field name differs, note the correct one.
- [ ] **1.4 Start** — `curl -s -u "$AUTH" -X POST "$BASE/api/v4/tests/$TEST/start" | jq '.result.id'`
  Pass: a numeric master ID (call it `$MASTER`).
- [ ] **1.5 Status vocabulary** — poll `curl -s -u "$AUTH" "$BASE/api/v4/masters/$MASTER/status" | jq -r '.result.status'`
  every ~15 s until the test finishes. Write down **every** value you see.
  Pass: the final value is `ENDED` for a normal finish. Also stop one run from the UI and
  record its final value (the script expects `ABORTED`), and if possible one that fails (`ERROR`).
- [ ] **1.6 Summary report** — `curl -s -u "$AUTH" "$BASE/api/v4/masters/$MASTER/reports/main/summary" | jq . | head`
  Pass: JSON with summary data (not an error object).
- [ ] **1.7 Full script** — inside the generated BlazeMeter setup:
  `./scripts/run-blazemeter.sh --test-case "<env>: <scenario>" --timeout-minutes 30`
  Pass: exit code 0, and `run-output/<env>_<scenario>/run-summary.json` has `"status": "passed"`,
  `"artifact_status": "complete"`, and a `report_link` that opens the run in BlazeMeter.

If 1.3, 1.5 or 1.6 differ from what's expected, the fix is in
`src/pipeline_generator/renderers/scripts.py` (`_render_blazemeter_script`).

---

## 2. LoadRunner Professional on a real Windows agent (≈1 h)

Use the Windows machine next to the LoadRunner Controller, with the CI agent
(GitHub runner, Azure agent or Jenkins agent) installed on it.

- [ ] **2.1 bash on the agent's PATH** — install Git for Windows. Add
  `C:\Program Files\Git\bin` (GitHub/Azure) or `C:\Program Files\Git\usr\bin`
  (Jenkins) to the agent service's PATH **ahead of** `C:\Windows\System32`,
  then restart the agent service. In a pipeline step, run `which bash; bash --version`.
  Pass: Git's bash (`/usr/bin/bash`, "GNU bash ... msys"), **not** WSL.
- [ ] **2.2 Line endings** — after checkout on the agent, run `file scripts/run-loadrunner_professional.sh`
  (or `head -1 ... | od -c`). Pass: no `\r`. (Requires the generated `scripts/.gitattributes` to be committed.)
- [ ] **2.3 wlrun found** — `command -v wlrun` (or your `wlrun_path`) from the agent's bash.
  Pass: prints a path. If `wlrun_path` is a full path, write it with forward slashes.
- [ ] **2.4 `.lrs` path check** — with `verify_scenario_exists` enabled, run the manual pipeline for a pair whose
  identifier is a real `C:\...\x.lrs`. Pass: the run gets past "Scenario file not found".
  Then try a deliberately wrong path. Pass: it stops with "Scenario file not found".
- [ ] **2.5 wlrun from the agent account** — trigger the manual pipeline for one short scenario.
  Pass: the Controller runs the scenario to completion. If it hangs or fails to open, the agent likely
  runs as a Windows service in session 0: reconfigure it to run as an interactive (logged-in) user and retry.
  Record which mode worked.
- [ ] **2.6 Results location** — after 2.5, check `run-output/<env>_<scenario>/` in the job's workspace.
  Pass: it contains LoadRunner's results files, and the uploaded artifact is not empty.
  If results appeared elsewhere (e.g. under the Controller's results directory), record where.
- [ ] **2.7 Exit code honesty** — run one scenario that has errors. Record `wlrun`'s exit code and
  `run-summary.json`'s `status`. (Known risk: some LoadRunner versions return 0 on a failed scenario.)

---

## 3. One real run per CI/CD platform (≈30 min each)

Use a JMeter setup on a hosted runner (fastest to get green), plus the
BlazeMeter credentials check. Repeat the LoadRunner variant on the Windows
agent from section 2 if that's your target.

### GitHub Actions
- [ ] **3.1** Repository secrets `BLAZEMETER_API_KEY_ID`/`_SECRET` created (BlazeMeter setups only).
- [ ] **3.2 Manual run** — Actions → manual workflow → Run workflow. Pass: one **Test case** dropdown listing
  exactly your `<environment>: <scenario>` pairs, load inputs pre-filled from `customer.yaml`; the run is green
  and the `performance-results` artifact contains `run-summary.json`.
- [ ] **3.3 Override** — run again with **users** changed. Pass: `run-summary.json` shows the new value.
- [ ] **3.4 Automated job** — call the reusable workflow from another workflow:
  ```yaml
  jobs:
    perf:
      uses: ./.github/workflows/performance-automated-<job>.yml
      secrets: inherit
  ```
  Pass: it runs without inputs and uses `customer.yaml`'s values. For BlazeMeter, also try **without**
  `secrets: inherit`. Pass: GitHub refuses to start it (required secret missing).
- [ ] **3.5 Runner** — if `cicd.runner` is set, confirm the job lands on that runner.

### Azure DevOps
- [ ] **3.6** Secret pipeline variables `BLAZEMETER_API_KEY_ID`/`_SECRET` (BlazeMeter setups only).
- [ ] **3.7 Manual run** — register `azure/performance-manual.yml` as a pipeline and run it. Pass: one
  **Environment and scenario** parameter limited to your pairs, load parameters pre-filled, green run,
  `performance-results` artifact published.
- [ ] **3.8 Automated template** — in another pipeline, under `jobs:` add
  `- template: azure/performance-automated-<job>.yml`. Pass: the job runs. For BlazeMeter, define the
  secret variables on **this** pipeline. Then remove one and rerun. Pass: the script stops with
  "BLAZEMETER_API_KEY_ID is not defined" (not a 401 later).
- [ ] **3.9 Pool** — if `cicd.runner` is a self-hosted pool name, confirm the job uses that pool.

### Jenkins
- [ ] **3.10** Credential **Username with password**, ID `blazemeter-api-key` (BlazeMeter setups only).
  Optionally tick "Treat username as secret".
- [ ] **3.11 Manual run** — create a Pipeline job from `jenkins/Jenkinsfile.performance-manual`. The first
  build only registers parameters; run **Build with Parameters**. Pass: **TEST_CASE** choice limited to your
  pairs, load string parameters pre-filled, green build, `run-output/**` archived.
- [ ] **3.12 Automated job** — create a job from the automated Jenkinsfile and start it from another job with
  `build job: '<name>'`. Pass: it runs with `customer.yaml`'s values; credentials masked in the console log.
- [ ] **3.13 Agent** — if `cicd.runner` is set, confirm the build runs on an agent with that label.

---

## Results

| Check | Result (pass / fail / n/a) | Notes (actual values, field names, errors) | Who / date |
|---|---|---|---|
| 1.1–1.2 BlazeMeter lookups | | | |
| 1.3 overrideExecutions | | | |
| 1.5 status values seen | | | |
| 1.6 summary endpoint | | | |
| 1.7 full BlazeMeter script | | | |
| 2.1 Git Bash on agent PATH | | | |
| 2.2 LF line endings | | | |
| 2.4 `.lrs` path check | | | |
| 2.5 wlrun service vs interactive | | | |
| 2.6 results location | | | |
| 2.7 wlrun exit code | | | |
| 3.2–3.5 GitHub Actions | | | |
| 3.7–3.9 Azure DevOps | | | |
| 3.11–3.13 Jenkins | | | |

Anything that fails: open an issue with the check number and the notes
column, so the fix lands in the generator rather than in a hand-edited copy.
