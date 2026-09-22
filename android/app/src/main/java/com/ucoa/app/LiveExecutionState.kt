package com.ucoa.app

import java.util.concurrent.CopyOnWriteArrayList

/** In-process live execution state rendered inside the conversation UI. */
object LiveExecutionState {
    data class Snapshot(
        val task: String = "",
        val phase: String = "",
        val action: String = "",
        val step: Int = 0,
        val maxSteps: Int = 60,
        val verified: Boolean? = null,
        val screenshotBase64: String? = null,
        val screenWidth: Int = 0,
        val screenHeight: Int = 0,
        val tapX: Float? = null,
        val tapY: Float? = null,
        val active: Boolean = false
    )

    private val listeners = CopyOnWriteArrayList<(Snapshot) -> Unit>()
    @Volatile private var snapshot = Snapshot()

    fun current(): Snapshot = snapshot

    fun subscribe(listener: (Snapshot) -> Unit): () -> Unit {
        listeners += listener
        listener(snapshot)
        return { listeners -= listener }
    }

    fun begin(task: String) {
        publish(snapshot.copy(task = task, active = true, phase = "تهيئة المهمة", action = "انتظار قرار Cloud AI", step = 0, verified = null))
    }

    fun update(
        task: String = snapshot.task,
        phase: String,
        action: String,
        step: Int,
        maxSteps: Int = 60,
        verified: Boolean? = null,
        screenshotBase64: String? = snapshot.screenshotBase64,
        screenWidth: Int = snapshot.screenWidth,
        screenHeight: Int = snapshot.screenHeight,
        tapX: Float? = null,
        tapY: Float? = null
    ) {
        publish(Snapshot(task, phase, action, step, maxSteps, verified, screenshotBase64, screenWidth, screenHeight, tapX, tapY, true))
    }

    fun finish(success: Boolean, message: String) {
        publish(snapshot.copy(phase = if (success) "اكتملت المهمة" else "توقفت المهمة", action = message, verified = success, active = false))
    }

    private fun publish(next: Snapshot) {
        snapshot = next
        listeners.forEach { runCatching { it(next) } }
    }
}
