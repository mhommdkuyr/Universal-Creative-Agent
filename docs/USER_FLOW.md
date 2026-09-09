# User flow

1. Launch the app.
2. Tap **ربط الهاتف بنقرة واحدة**.
3. Android opens Accessibility settings. Enable **Universal Creative Agent** once, then return to the app.
4. The app checks the real Android accessibility state in `onResume()` and shows `● متصل` when the service is alive.
5. Type a natural-language task, speak it, or attach media.
6. The app classifies the task and shows a human-readable execution plan.
7. Choose **مراجعة وتعديل** to edit the plan, or **تنفيذ الآن** to approve it.
8. Attached media is queued for local background preparation through WorkManager.

## Important Android limitation

A normal Android application cannot silently grant itself Accessibility access, and AccessibilityService is not a general-purpose background automation channel for manipulating arbitrary other apps without their UI being active. The product therefore keeps permission setup minimal and explicit, while allowing media preparation to run in the background. Foreground GUI execution remains permission- and target-app-dependent.
