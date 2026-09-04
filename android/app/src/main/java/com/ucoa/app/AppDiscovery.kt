package com.ucoa.app

import android.content.Context
import android.content.pm.PackageManager

object AppDiscovery {
    fun findPackage(context: Context, userName: String): String? {
        val wanted = userName.trim().lowercase()
        if (wanted.isEmpty()) return null
        val pm = context.packageManager
        val apps = pm.getInstalledApplications(PackageManager.ApplicationInfoFlags.of(0))
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
