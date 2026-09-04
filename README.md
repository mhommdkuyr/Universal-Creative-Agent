# Universal Creative Agent

Universal Creative Agent (UCOA) is an agent runtime for high-level creative and computer-use tasks. It routes work across mobile GUI automation, browser automation, video understanding, visual design, and software engineering while keeping planning, execution, and verification separate.

## Current scope

- Task routing: creative replication, video editing, design, software engineering, browser automation, general agent.
- Reference analysis for local video/image assets using FFprobe/OpenCV/Pillow.
- Creative blueprint generation from reference media.
- Pluggable execution adapters for Android, browser-use, OpenHands, and deterministic tests.
- Verification and repair loop contracts.
- Android Accessibility Service action bridge for tap/swipe/long-press/type/open/back/home.

## High-level flow

`User request -> Router -> Reference/Context Analysis -> Planner -> Skills/Adapters -> Execute -> Observe -> Verify -> Repair -> Deliver`

## Run tests

```bash
pytest -q
```

The Android module is under `android/`. Building the APK requires a local Android SDK/Gradle environment.

## Roadmap

The next milestones are real provider execution, multimodal reference understanding, Browser Use integration, OpenHands coding integration, Android screenshot/UI-tree observation, and app-specific skills for creative tools such as CapCut/Canva/Figma.
