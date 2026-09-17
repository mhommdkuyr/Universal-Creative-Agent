package com.ucoa.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class UcoaAccessibilityServiceTest {

    @Test
    fun testAccessibilityServiceEnabledAutomationAndTargetGesture() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val device = UiDevice.getInstance(instrumentation)

        // Enable the project's AccessibilityService through the real device shell.
        device.executeShellCommand(
            "settings put secure enabled_accessibility_services com.ucoa.app/.UcoaAccessibilityService"
        )
        device.executeShellCommand("settings put secure accessibility_enabled 1")

        val enabledServices = device.executeShellCommand(
            "settings get secure enabled_accessibility_services"
        )
        assertTrue(
            "UcoaAccessibilityService is not enabled",
            enabledServices.contains("com.ucoa.app/.UcoaAccessibilityService")
        )

        var service: UcoaAccessibilityService? = null
        repeat(20) {
            service = UcoaAccessibilityService.instance
            if (service != null) return@repeat
            Thread.sleep(500)
        }
        assertNotNull("UcoaAccessibilityService instance should connect", service)

        // Launch a real target application through the AccessibilityService itself.
        assertTrue("AccessibilityService failed to launch Settings", service!!.openApp("com.android.settings"))
        assertTrue(
            "Settings did not reach foreground",
            device.wait(Until.hasObject(By.pkg("com.android.settings")), 8_000)
        )

        // Exercise an actual AccessibilityService gesture on the target UI.
        device.waitForIdle()
        val width = device.displayWidth
        val height = device.displayHeight
        val swipeAccepted = service!!.swipe(
            width * 0.50f,
            height * 0.70f,
            width * 0.50f,
            height * 0.35f,
            450
        )
        assertTrue("AccessibilityService swipe gesture was rejected", swipeAccepted)

        // Final foreground verification must still be the target app after the gesture.
        assertTrue(
            "Target app lost foreground after gesture",
            device.currentPackageName == "com.android.settings"
        )
    }
}
