package com.ucoa.app

import org.junit.Assert.assertNotNull
import org.junit.Test

class TaskExecutionModeTest {
    @Test fun bothExecutionModesExist() {
        assertNotNull(TaskExecutionMode.FOREGROUND_GUI)
        assertNotNull(TaskExecutionMode.BACKGROUND_MEDIA)
    }
}
