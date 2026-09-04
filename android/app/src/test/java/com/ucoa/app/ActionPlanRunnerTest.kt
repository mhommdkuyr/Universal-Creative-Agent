package com.ucoa.app

import org.junit.Assert.assertEquals
import org.junit.Test

class ActionPlanRunnerTest {
    @Test fun messageModelKeepsPlanData() {
        val message = ChatMessage("assistant", "الخطة", listOf("تحليل", "تنفيذ"), "task-1")
        assertEquals("task-1", message.taskId)
        assertEquals(2, message.plan.size)
    }
}
