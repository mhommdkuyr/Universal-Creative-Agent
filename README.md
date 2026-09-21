# Universal Creative Agent (UCOA)

Universal AI agent for mobile GUI, browser, video, design, and coding workflows.

## Current architecture

The production release architecture is **cloud-only for AI/model execution**:

- **Android:** chat UI, voice/media input, explicit Accessibility permission flow, observation, UI action execution, screenshots/UI-tree evidence, and result verification.
- **Cloud:** planning, reasoning, vision, provider routing/failover, durable state, telemetry, and verification.
- Provider/model secrets remain server-side and are never embedded in the APK.

The backend exposes the FastAPI app through `server/app.py` and the Vercel-compatible Python entrypoint at `api/index.py`.

## Release gates

A release is not considered verified until the exact APK built from the release commit passes:

1. Python/server tests.
2. Android unit/instrumentation build checks.
3. Cloud contract checks.
4. A physical Android acceptance run that proves execution through `UcoaAccessibilityService`, device evidence, foreground state, and durable command completion.
5. APK SHA-256 and evidence artifacts are retained with the release record.

The project does **not** claim invisible universal background manipulation of arbitrary third-party applications. Foreground execution remains constrained by Android Accessibility and target-app behavior.

## Development verification

`pytest -q` from the repository root runs the Python suite.
