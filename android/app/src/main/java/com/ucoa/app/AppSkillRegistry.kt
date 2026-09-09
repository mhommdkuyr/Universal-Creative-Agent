package com.ucoa.app

/**
 * Resolves human-friendly targets into deterministic execution skills.
 * Skills are intentionally data-driven so more apps can be added without
 * changing the agent execution loop.
 */
object AppSkillRegistry {
    data class Skill(
        val id: String,
        val aliases: List<String>,
        val packageAliases: List<String> = emptyList(),
        val webUrl: String? = null,
        val actions: List<String>
    )

    private val skills = listOf(
        Skill(
            id = "ai_creative_studio",
            aliases = listOf("ai creative studio", "ai creative", "creative studio", "استوديو إبداعي", "ai كريتيف"),
            webUrl = "https://ai-creative-studio.app/",
            actions = listOf("open_target", "observe", "select_video", "fill_prompt", "observe_result")
        ),
        Skill(
            id = "capcut",
            aliases = listOf("capcut", "كاب كات"),
            packageAliases = listOf("capcut"),
            actions = listOf("open_target", "observe", "execute")
        ),
        Skill(
            id = "canva",
            aliases = listOf("canva", "كانفا"),
            packageAliases = listOf("canva"),
            actions = listOf("open_target", "observe", "execute")
        ),
        Skill(
            id = "chrome",
            aliases = listOf("chrome", "كروم", "المتصفح"),
            packageAliases = listOf("chrome"),
            actions = listOf("open_target", "observe", "execute")
        )
    )

    fun resolve(text: String): Skill? {
        val normalized = text.trim().lowercase()
        return skills.sortedByDescending { it.aliases.maxOfOrNull { alias -> alias.length } ?: 0 }
            .firstOrNull { skill -> skill.aliases.any { normalized.contains(it) } }
    }
}
