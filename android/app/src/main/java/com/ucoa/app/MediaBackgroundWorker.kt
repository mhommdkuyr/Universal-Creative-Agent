package com.ucoa.app

import android.content.Context
import android.net.Uri
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters

class MediaBackgroundWorker(appContext: Context, params: WorkerParameters) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        val task = inputData.getString("task") ?: return Result.failure()
        val uris = inputData.getStringArray("media_uris") ?: emptyArray()
        if (task.isBlank()) return Result.failure()

        val prepared = uris.mapNotNull { raw ->
            runCatching {
                val uri = Uri.parse(raw)
                val mime = applicationContext.contentResolver.getType(uri) ?: "application/octet-stream"
                val size = applicationContext.contentResolver.openAssetFileDescriptor(uri, "r")?.use { it.length } ?: -1L
                "$raw|$mime|$size"
            }.getOrNull()
        }
        applicationContext.getSharedPreferences("ucoa_background", Context.MODE_PRIVATE)
            .edit()
            .putInt("last_prepared_count", prepared.size)
            .putString("last_task", task)
            .apply()
        return Result.success()
    }
}
