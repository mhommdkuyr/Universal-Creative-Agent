# UCOA Architecture

## Core loop

1. Intent and context normalization.
2. Route selection.
3. Reference understanding (video/image/document when available).
4. Creative blueprint generation for reference-driven work.
5. Plan decomposition into checkpoints.
6. Skill/adapter selection.
7. Observe -> act -> observe execution loop.
8. Render/export when the target supports it.
9. Verification against explicit quality metrics.
10. Repair/re-run on deviations.

## Execution strategy

UCOA intentionally supports three execution modes:

- GUI: Accessibility/screenshot/gesture interaction for arbitrary Android applications.
- Browser/native: browser automation or application-native APIs when they are more precise.
- Artifact-level: FFmpeg, project files, code tools, and other deterministic operations.

The router should choose the least fragile execution surface that still satisfies the requested outcome. GUI remains the universal fallback for controls a human can see and operate.

## Reference replication

A reference URL or file is not converted straight into clicks. It is converted into a Creative Blueprint containing timeline/scene observations, visual style, audio metadata, typography placeholders, and fidelity constraints. A future multimodal provider fills the semantic fields; the deterministic analyzer already provides local media metadata and scene sampling.

## Target integrations

- Android: AccessibilityService + screenshot/UI-tree observation + optional Shizuku.
- Browser: Browser Use / Midscene.
- Video: FFmpeg + reference analysis + target-app GUI skill.
- Design: application-specific skills for Canva/Figma/Photoshop-class editors.
- Coding: OpenHands-compatible coding agent and browser verification.
