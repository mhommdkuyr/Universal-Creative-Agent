Final release acceptance is driven from the CI workflow completion and then runs the cloud contract, thin-client APK checks, Android x86_64 emulator smoke, accessibility action, and cloud verification before uploading the verified APK.

## Physical acceptance progress — 2026-09-18

- Merged the existing Jules PR #16 into `main`; no new Jules task was started.
- GitHub Actions launched the real-device workflow for commit `dcc97eab503e9462dd02029f63da577daedbfde5`.
- Firebase Test Lab reached the real-device execution gate and selected physical device `yogi / Android 37`.
- APK build, cloud-only APK verification, Google authentication, device discovery, and results-bucket discovery all passed.
- The Test Lab invocation stopped before creating a Test Matrix because Firebase attempted to create/use `chatapp-62912.appspot.com` and returned a permission/billing error. Therefore this run is **not** physical-device acceptance and must not be marked successful.
- Corrective step committed on `main`: normalize the results bucket to `gs://...`, add a bucket read/write preflight, and use a unique `results-dir` for the next physical run.
- Final acceptance rule remains: only a completed Firebase Test Lab physical matrix with `outcomeSummary=SUCCESS` counts as real-device success; emulator/build success does not.
