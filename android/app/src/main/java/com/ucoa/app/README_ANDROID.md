# Android client

The client is intentionally a single-screen conversational control surface. The user grants Accessibility once; after returning from Android settings, the client re-checks the permission automatically.

The composer supports text, speech recognition, and media attachments. Every task is first interpreted into a visible plan with review/edit and execute actions.

Media attachments are handed to a WorkManager background preparation job. Third-party UI automation is dispatched through AccessibilityService when the target app is active and the platform allows the action.
