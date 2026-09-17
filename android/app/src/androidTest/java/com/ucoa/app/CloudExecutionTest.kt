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
        return device.currentPackageName.orEmpty()
    }

    @Test
    fun realCloudExecution() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val device = UiDevice.getInstance(instrumentation)

        shell(device, "settings put secure enabled_accessibility_services com.ucoa.app/.UcoaAccessibilityService")
        shell(device, "settings put secure accessibility_enabled 1")
        shell(device, "am force-stop com.android.settings")
        shell(device, "am force-stop com.ucoa.app")

        val intent = Intent(context, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            putExtra("smoke_task", "افتح الإعدادات")
        }
        context.startActivity(intent)

        val approval = device.wait(Until.findObject(By.text("تنفيذ عالمي")), 180_000)
        assertNotNull("Cloud plan approval button did not appear", approval)
        approval!!.click()

        var reachedSettings = false
        repeat(180) {
            if (foregroundPackage(device).contains("com.android.settings")) {
                reachedSettings = true
                return@repeat
            }
            Thread.sleep(1000)
        }
        assertTrue("Android action did not open Settings", reachedSettings)
        assertEquals("com.android.settings", foregroundPackage(device))

        val logcat = shell(device, "logcat -d")
        assertTrue("Real smoke success marker missing", logcat.contains("UCOA_REAL_SMOKE_OK"))
    }
}
