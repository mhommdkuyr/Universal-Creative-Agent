package com.ucoa.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class UcoaAccessibilityServiceTest {

    @Test
    fun testAccessibilityServiceEnabledAndAutomation() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val device = UiDevice.getInstance(instrumentation)

        // Enable AccessibilityService using UiDevice shell execution
        device.executeShellCommand("settings put secure enabled_accessibility_services com.ucoa.app/.UcoaAccessibilityService")
        device.executeShellCommand("settings put secure accessibility_enabled 1")

        // Verify enabled services settings property contains UcoaAccessibilityService
        val enabledServices = device.executeShellCommand("settings get secure enabled_accessibility_services")
        assertTrue(
            "Accessibility service com.ucoa.app/.UcoaAccessibilityService is not enabled",
            enabledServices.contains("com.ucoa.app/.UcoaAccessibilityService")
        )

        // Verify service instance connection or UI interaction
        repeat(10) {
            if (UcoaAccessibilityService.instance != null) return@repeat
            Thread.sleep(500)
        }
        val service = UcoaAccessibilityService.instance
        assertNotNull("UcoaAccessibilityService instance should connected", service)

        // Test basic UI automation / gesture capability on device
        val homeSuccess = service?.home() ?: false
        assertTrue("Global HOME action execution failed", homeSuccess)
    }
}
