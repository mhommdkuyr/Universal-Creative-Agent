package com.ucoa.app

import android.app.Activity
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import java.util.Locale

/** Real-app smoke harness. It drives the installed CapCut package through Accessibility. */
class UcoaCapCutSmokeActivity : Activity() {
    private val main = Handler(Looper.getMainLooper())
    private var finished = false
    private var usefulActions = 0
    private var verifiedActions = 0
    private var capCutPackage: String? = null
    private lateinit var loop: UniversalAgentLoop
    private lateinit var brain: AgentBrainClient

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        brain = AgentBrainClient(this)
        val label = intent.getStringExtra("capcut_label") ?: "CapCut"
        capCutPackage = findPackage(label)
        Log.i(TAG, "UCOA_CAPCUT_SMOKE_START package=$capCutPackage")
        waitForService(0)
    }

    private fun waitForService(attempt: Int) {
        if (finished) return
        if (UcoaAccessibilityService.instance != null) {
            startAgent()
            return
        }
        if (attempt >= 45) return fail("accessibility service unavailable")
        main.postDelayed({ waitForService(attempt + 1) }, 400)
    }

    private fun startAgent() {
        val task = "Open CapCut and reach its video editing workspace. If it asks for a new project, create one and choose the first available video. Continue navigating through visible screens until the CapCut editor/timeline is visible. Stop only when the editor is visibly confirmed. Never guess a control."
        loop = UniversalAgentLoop(brain)
        loop.start(task, object : UniversalAgentLoop.Listener {
            override fun onEvent(text: String) {
                Log.i(TAG, "UCOA_CAPCUT_EVENT $text")
                if (text.startsWith("التنفيذ:") && !text.contains("observe", true)) usefulActions++
                if (text.contains("التحقق: نجح", true)) verifiedActions++
                main.postDelayed({ inspectState() }, 250)
            }
            override fun onConfirmationRequired(reasons: String) { fail("confirmation required: $reasons") }
            override fun onFinished(success: Boolean) {
                main.post {
                    if (finished) return@post
                    if (success && isEditorVisible()) {
                        Log.i(TAG, "UCOA_CAPCUT_SMOKE_OK actions=$usefulActions verified=$verifiedActions package=${foregroundPackage()}")
                        finished = true
                        finish()
                    } else {
                        fail("agent finished success=$success actions=$usefulActions verified=$verifiedActions foreground=${foregroundPackage()}")
                    }
                }
            }
        })
    }

    private fun inspectState() {
        if (finished) return
        if (isEditorVisible() && usefulActions >= 1) {
            Log.i(TAG, "UCOA_CAPCUT_EDITOR_CONFIRMED actions=$usefulActions verified=$verifiedActions package=${foregroundPackage()}")
            loop.stop()
            finished = true
            Log.i(TAG, "UCOA_CAPCUT_SMOKE_OK actions=$usefulActions verified=$verifiedActions package=${foregroundPackage()}")
            finish()
        }
    }

    private fun isEditorVisible(): Boolean {
        val pkg = foregroundPackage() ?: return false
        if (capCutPackage != null && pkg != capCutPackage) return false
        val ui = UcoaAccessibilityService.instance?.observeUi(500)?.lowercase(Locale.ROOT) ?: return false
        // These are broad editor signals; the model is responsible for the actual path.
        return listOf("timeline", "audio", "text", "split", "speed", "canvas", "export", "add audio", "tracks").count { ui.contains(it) } >= 2
    }

    private fun foregroundPackage(): String? = UcoaAccessibilityService.instance?.foregroundPackageName()

    private fun findPackage(label: String): String? {
        val pm = packageManager
        return pm.getInstalledApplications(0).firstOrNull {
            (pm.getApplicationLabel(it)?.toString() ?: "").contains(label, true)
        }?.packageName
    }

    private fun fail(reason: String): Nothing {
        if (!finished) {
            finished = true
            Log.e(TAG, "UCOA_CAPCUT_SMOKE_FAILED $reason")
            loopOrNullStop()
        }
        finish()
        throw IllegalStateException(reason)
    }

    private fun loopOrNullStop() { runCatching { if (::loop.isInitialized) loop.stop() } }

    companion object { private const val TAG = "UCOA_CAPCUT" }
}
