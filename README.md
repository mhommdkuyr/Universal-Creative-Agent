# Universal Creative Agent

Universal Creative Agent (UCOA) is an agent runtime for high-level creative and computer-use tasks. It routes work across mobile GUI automation, browser automation, video understanding, visual design, and software engineering while keeping planning, execution, and verification separate.

## Current scope

- Task routing: creative replication, video editing, design, software engineering, browser automation, general agent.
- Reference analysis for local video/image assets using FFprobe/OpenCV/Pillow.
- Creative blueprint generation from reference media.
- Pluggable execution adapters for Android, browser-use, OpenHands, and deterministic tests.
- Verification and repair loop contracts.
- Android Accessibility Service action bridge for tap/swipe/long-press/type/open/back/home.
- Bounded autonomous repository development through an OpenAI-compatible gateway.

## High-level flow

`User request -> Router -> Reference/Context Analysis -> Planner -> Skills/Adapters -> Execute -> Observe -> Verify -> Repair -> Deliver`

## Run tests

```bash
pytest -q
```

The Android module is under `android/`. Building the APK requires a local Android SDK/Gradle environment.

## AI gateway configuration

The autonomous developer uses the OpenAI-compatible Experiential Labs endpoint:

```text
POST https://api.experientiallabs.ai/v1/chat/completions
Authorization: Bearer $EXPLABS_API_KEY
Content-Type: application/json
```

The default model is `claude-fable-5.1`. The key is read only from the runtime environment; it is never written to the repository or included in the repository snapshot sent to the model. For backwards compatibility, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL` remain supported as fallbacks.

The GitHub Actions autonomous workflow prefers the `EXPLABS_API_KEY` secret and falls back to the existing `OPENAI_API_KEY` secret. The workflow is limited to an isolated branch and pull request, with repository/workflow/secrets paths excluded from model edits.

## Roadmap

Next milestones include multimodal reference understanding, Browser Use integration, OpenHands coding integration, Android screenshot/UI-tree observation, and app-specific skills for creative tools such as CapCut/Canva/Figma.
