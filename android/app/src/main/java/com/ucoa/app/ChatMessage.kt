package com.ucoa.app

data class ChatMessage(
    val role: String,
    val text: String,
    val plan: List<String> = emptyList(),
    val taskId: String? = null
)
