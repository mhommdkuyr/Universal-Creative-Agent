# Current

The Android client work in this branch is validated through GitHub Actions.

## Latest physical-device attempt — 2026-09-18

Status: **blocked before Test Matrix creation**.

The workflow reached Firebase Test Lab and identified a physical device (`yogi`, Android 37), but the test command exited with code 1 because of a results-bucket permission/billing error involving `chatapp-62912.appspot.com`. No physical execution result was produced, so this is not an app-success result.

Next automated step already committed to `main`: pass the results bucket as `gs://...`, verify bucket read/write access, and use a unique results directory before retrying the physical test.

## Physical acceptance blocker — 2026-09-18

- The next physical-device attempt reached the Firebase Test Lab workflow and passed APK build, cloud-only APK validation, Google authentication, and physical-device discovery.
- Physical device discovery is therefore working; the workflow was able to reach the physical-device gate.
- The run stopped before Firebase created a Test Matrix because no usable Cloud Storage results bucket exists in project `chatapp-62912`.
- The workflow first confirmed that `gs://chatapp-62912.appspot.com` does not exist (HTTP 404), then attempted to create `gs://ucoa-ftl-results-chatapp-62912`.
- Google Cloud returned HTTP 403: `The billing account for the owning project is disabled in state absent`. Therefore the blocker is project billing/storage infrastructure, not an Android build or application execution failure.
- The workflow now supports a preconfigured `FIREBASE_TEST_RESULTS_BUCKET` or `RESULTS_BUCKET` secret and will otherwise try to provision its own results bucket when billing permits.
- This run produced **no physical-device execution result** and must not be reported as app success.
- Required next gate: a billing-enabled GCS bucket accessible for Firebase Test Lab results, followed by a completed physical Test Matrix with `outcomeSummary=SUCCESS` and the real execution assertions passing.

## Live phone test started — 2026-09-18 22:02 +03:00

A cloud-to-phone live validation cycle was started after installing the corrected APK. Acceptance requires UCOA-owned live overlay evidence plus post-action UI verification; opening an external app alone is not sufficient.
