# Test checklist

## Automated

- Python: `pytest -q`
- Android: `gradle -p android test`
- Android package: `gradle -p android assembleDebug`
- Emulator: install produced APK, launch `com.ucoa.app/.MainActivity`, verify process and activity.

## Manual device

- Launch app.
- Tap **ربط الهاتف بنقرة واحدة**.
- Enable the service in Android Accessibility settings.
- Return to the app and verify `● متصل`.
- Enter a simple task and verify plan card appears.
- Edit the plan and verify edited steps are stored in the active plan.
- Attach a media file and verify the WorkManager job is enqueued.
- For supported GUI actions, verify action result is shown as `OK` or `FAILED` rather than a false success.
