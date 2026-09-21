package com.ucoa.app

import android.content.Intent
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CloudExecutionTest {
    private fun shell(device: UiDevice, command: String): String = device.executeShellCommand(command)

    private fun foregroundPackage(device: UiDevice): String {
        val focus = shell(device, "dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp'")
        val pkg = focus.substringAfter("u0 ", "").substringBefore("/").trim()
        if (pkg.isNotEmpty() && !pkg.contains(" ")) return pkg
        val top = shell(device, "dumpsys activity top | grep -m1 ACTIVITY")
        return top.substringAfter("ACTIVITY ", "").substringBefore("/").trim()
    }

    private fun runSettingsTask(device: UiDevice, context: android.content.Context, taskLabel: String) {
        val intent = Intent(context, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            putExtra("smoke_task", taskLabel)
        }
        context.startActivity(intent)

        val approval = device.wait(Until.findObject(By.text("تنفيذ عالمي")), 180_000)
        assertNotNull("Cloud plan approval button did not appear for task: $taskLabel", approval)
        approval!!.click()

        var reachedSettings = false
        repeat(180) {
            if (foregroundPackage(device).contains("com.android.settings")) {
                reachedSettings = true
                return@repeat
            }
            Thread.sleep(1000)
        }
        assertTrue("Android action did not open Settings for task: $taskLabel", reachedSettings)
        assertTrue(
            "Foreground package is not Settings: " + foregroundPackage(device),
            foregroundPackage(device).contains("com.android.settings")
        )

        val logcat = shell(device, "logcat -d")
        assertTrue("Real smoke success marker missing for task: $taskLabel", logcat.contains("UCOA_REAL_SMOKE_OK"))
    }

    @Test
    fun realCloudExecutionTwoSafeTasks() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val device = UiDevice.getInstance(instrumentation)

        shell(device, "settings put secure enabled_accessibility_services com.ucoa.app/.UcoaAccessibilityService")
        shell(device, "settings put secure accessibility_enabled 1")
        shell(device, "am force-stop com.android.settings")
        shell(device, "am force-stop com.ucoa.app")

        runSettingsTask(device, context, "افتح الإعدادات")
        device.pressHome()
        Thread.sleep(1500)
        runSettingsTask(device, context, "افتح الإعدادات مرة أخرى")
    }
}
