package com.ucoa.app

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build

object AppDiscovery {
    fun findPackage(context: Context, userName: String): String? {
        val wanted = userName.trim().lowercase()
        if (wanted.isEmpty()) return null
        val pm = context.packageManager
        @Suppress("DEPRECATION")
        val apps = if (Build.VERSION.SDK_INT >= 33) {
            pm.getInstalledApplications(PackageManager.ApplicationInfoFlags.of(0))
        } else {
            pm.getInstalledApplications(0)
        }
        return apps.firstNotNullOfOrNull { info ->
            val label = pm.getApplicationLabel(info).toString().lowercase()
            when {
                label == wanted || label.contains(wanted) -> info.packageName
                normalize(label).contains(normalize(wanted)) -> info.packageName
                else -> null
            }
        }
    }

    private fun normalize(value: String): String = value
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
}
