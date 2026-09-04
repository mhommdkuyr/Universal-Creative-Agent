package com.ucoa.app

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters

class MediaBackgroundWorker(appContext: Context, params: WorkerParameters) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        val task = inputData.getString("task") ?: return Result.failure()
        val mediaCount = inputData.getInt("media_count", 0)
        // The worker intentionally performs only safe local preparation here.
        // App GUI actions remain in AccessibilityService because Android does not
        // permit an ordinary app to silently manipulate another app's UI in the background.
        return if (task.isNotBlank() && mediaCount >= 0) Result.success() else Result.failure()
    }
}
