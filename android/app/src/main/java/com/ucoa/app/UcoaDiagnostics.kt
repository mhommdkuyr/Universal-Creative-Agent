package com.ucoa.app

import android.content.Context
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.CopyOnWriteArrayList

/** Lightweight on-device execution trace. It never persists authentication tokens. */
object UcoaDiagnostics {
    data class Event(val time: String, val stage: String, val message: String, val details: String = "") {
        fun line(): String = buildString {
            append(time).append("  ").append(stage).append("  ").append(message)
            if (details.isNotBlank()) append(" | ").append(details)
        }
    }

    private const val PREFS = "ucoa_diagnostics"
    private const val KEY = "events"
    private const val MAX_EVENTS = 220
    private val listeners = CopyOnWriteArrayList<(Event) -> Unit>()
    private val lock = Any()
    private var appContext: Context? = null
    private var events = mutableListOf<Event>()
    private val format = SimpleDateFormat("HH:mm:ss.SSS", Locale.US)

    fun init(context: Context) {
        synchronized(lock) {
            if (appContext != null) return
            appContext = context.applicationContext
            val saved = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, "").orEmpty()
            events = saved.lines().mapNotNull { parse(it) }.takeLast(MAX_EVENTS).toMutableList()
        }
    }

    fun log(stage: String, message: String, details: String = "") {
        val event = synchronized(lock) {
            val created = Event(format.format(Date()), stage, sanitize(message), sanitize(details))
            events.add(created)
            if (events.size > MAX_EVENTS) events = events.takeLast(MAX_EVENTS).toMutableList()
            persistLocked()
            created
        }
        listeners.forEach { runCatching { it(event) } }
    }

    fun recentText(): String = synchronized(lock) { events.joinToString("\n") { it.line() } }

    fun clear() {
        synchronized(lock) {
            events.clear()
            persistLocked()
        }
        log("DIAG", "تم مسح سجل التشخيص")
    }

    fun subscribe(listener: (Event) -> Unit): () -> Unit {
        listeners += listener
        return { listeners -= listener }
    }

    private fun persistLocked() {
        val ctx = appContext ?: return
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(KEY, events.joinToString("\n") { it.line() })
            .apply()
    }

    private fun sanitize(value: String): String = value
        .replace(Regex("(?i)Bearer\\s+[A-Za-z0-9._~+/=-]+"), "Bearer <redacted>")
        .replace(Regex("(?i)(token|api[_-]?key|authorization)=\\S+"), "$1=<redacted>")
        .replace("\u0000", "")
        .take(1400)

    private fun parse(line: String): Event? {
        val first = line.indexOf("  ")
        if (first <= 0) return null
        val second = line.indexOf("  ", first + 2)
        if (second <= first) return null
        val head = line.substring(0, first)
        val stage = line.substring(first + 2, second)
        val body = line.substring(second + 2)
        val separator = body.indexOf(" | ")
        return if (separator >= 0) Event(head, stage, body.substring(0, separator), body.substring(separator + 3))
        else Event(head, stage, body)
    }
}
