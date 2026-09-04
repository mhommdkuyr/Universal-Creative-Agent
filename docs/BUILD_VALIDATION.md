# Build validation

The release gate for the Android client is:

- Python tests pass.
- Android unit tests pass with `gradle -p android test`.
- Debug APK builds with `gradle -p android assembleDebug`.
- Emulator smoke installs the exact produced APK and launches `com.ucoa.app/.MainActivity`.

A green build confirms the client package is structurally runnable. It does not prove that arbitrary third-party apps can be manipulated invisibly in the background; Android Accessibility and each target app's own behavior determine that.
