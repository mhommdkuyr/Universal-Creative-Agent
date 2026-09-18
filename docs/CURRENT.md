# Current

The Android client work in this branch is validated through GitHub Actions.

## Latest physical-device attempt — 2026-09-18

Status: **blocked before Test Matrix creation**.

The workflow reached Firebase Test Lab and identified a physical device (`yogi`, Android 37), but the test command exited with code 1 because of a results-bucket permission/billing error involving `chatapp-62912.appspot.com`. No physical execution result was produced, so this is not an app-success result.

Next automated step already committed to `main`: pass the results bucket as `gs://...`, verify bucket read/write access, and use a unique results directory before retrying the physical test.
