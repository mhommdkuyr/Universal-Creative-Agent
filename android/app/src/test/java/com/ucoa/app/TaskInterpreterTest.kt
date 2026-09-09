package com.ucoa.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TaskInterpreterTest {
    @Test fun videoTasksProduceExecutionPlan() {
        val result = TaskInterpreter().analyze("حلل هذا الفيديو ونفذه في CapCut", listOf("content://video.mp4"))
        assertEquals("creative_video", result.taskType)
        assertTrue(result.steps.size >= 3)
    }

    @Test fun softwareTasksProduceImplementationPlan() {
        val result = TaskInterpreter().analyze("عدّل الكود وشغل الاختبارات", emptyList())
        assertEquals("software", result.taskType)
        assertTrue(result.steps.any { it.contains("الاختبارات") })
    }
}
