# Stage 2 implementation boundary

The Android client is intentionally split into:

- UI: ChatGPT-like composer, voice, attachments, plan/review/execute.
- Permission layer: one-tap navigation to Android Accessibility settings plus automatic return-state detection.
- Observation/control: AccessibilityService and action runner.
- Planning: local task interpretation with explicit plan objects.
- Background media: WorkManager preparation.
- Agent brain: the Python core in `core/ucoa`, where remote VLM/LLM providers and specialized skills can be connected.

The remaining integration work for true universal execution is to transport task/observation events between the Android client and the agent brain, then add app-specific skills and end-to-end verification. These are separate from the Android permission UX and should not be hidden behind fake success states.
