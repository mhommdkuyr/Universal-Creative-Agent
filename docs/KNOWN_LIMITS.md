# Current capability boundary

The Android client now provides direct chat interaction, voice input, media selection, a human-readable plan/review/execute workflow, real AccessibilityService state detection, installed-app discovery by label, action dispatch, and background local media preparation.

The full universal-agent loop still requires the agent brain and app skills to be connected to the Android client. In particular, arbitrary long natural-language tasks cannot yet be guaranteed to execute end-to-end across every third-party app from this APK alone. Background media preparation is supported, but Android does not provide a general permission for silently manipulating another app's UI while that app is not active.

No claim of universal background execution is made until an end-to-end device test proves it for the target app.
