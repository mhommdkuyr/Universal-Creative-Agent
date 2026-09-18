Final release acceptance is driven from the CI workflow completion and then runs the cloud contract, thin-client APK checks, Android x86_64 emulator smoke, accessibility action, and cloud verification before uploading the verified APK.

## Physical acceptance progress — 2026-09-18

- Merged the existing Jules PR #16 into `main`; no new Jules task was started.
- GitHub Actions launched the real-device workflow for commit `dcc97eab503e9462dd02029f63da577daedbfde5`.
- Firebase Test Lab reached the real-device execution gate and selected physical device `yogi / Android 37`.
- APK build, cloud-only APK verification, Google authentication, device discovery, and results-bucket discovery all passed.
- The Test Lab invocation stopped before creating a Test Matrix because Firebase attempted to create/use `chatapp-62912.appspot.com` and returned a permission/billing error. Therefore this run is **not** physical-device acceptance and must not be marked successful.
- Corrective step committed on `main`: normalize the results bucket to `gs://...`, add a bucket read/write preflight, and use a unique `results-dir` for the next physical run.
- Final acceptance rule remains: only a completed Firebase Test Lab physical matrix with `outcomeSummary=SUCCESS` counts as real-device success; emulator/build success does not.

## Physical acceptance blocker — 2026-09-18

- The next physical-device attempt reached the Firebase Test Lab workflow and passed APK build, cloud-only APK validation, Google authentication, and physical-device discovery.
- Physical device discovery is therefore working; the workflow was able to reach the physical-device gate.
- The run stopped before Firebase created a Test Matrix because no usable Cloud Storage results bucket exists in project `chatapp-62912`.
- The workflow first confirmed that `gs://chatapp-62912.appspot.com` does not exist (HTTP 404), then attempted to create `gs://ucoa-ftl-results-chatapp-62912`.
- Google Cloud returned HTTP 403: `The billing account for the owning project is disabled in state absent`. Therefore the blocker is project billing/storage infrastructure, not an Android build or application execution failure.
- The workflow now supports a preconfigured `FIREBASE_TEST_RESULTS_BUCKET` or `RESULTS_BUCKET` secret and will otherwise try to provision its own results bucket when billing permits.
- This run produced **no physical-device execution result** and must not be reported as app success.
- Required next gate: a billing-enabled GCS bucket accessible for Firebase Test Lab results, followed by a completed physical Test Matrix with `outcomeSummary=SUCCESS` and the real execution assertions passing.
