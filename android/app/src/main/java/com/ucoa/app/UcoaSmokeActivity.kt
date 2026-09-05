package com.ucoa.app

import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.widget.LinearLayout
import android.widget.TextView

/** CI-only style functional harness: harmless in-app button proves Accessibility execution and post-state verification. */
class UcoaSmokeActivity : android.app.Activity() {
    private lateinit var target: TextView
    private lateinit var status: TextView
    private val main = Handler(Looper.getMainLooper())
    private var visionSeen = false
    private var verificationSeen = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER; setPadding(40, 40, 40, 40) }
        status = TextView(this).apply { text = "UCOA smoke: starting…"; textSize = 18f; setTextColor(Color.DKGRAY); gravity = Gravity.CENTER }
        target = TextView(this).apply {
            text = "CONTINUE"; textSize = 30f; gravity = Gravity.CENTER; setTextColor(Color.BLACK); setBackgroundColor(Color.LTGRAY); isClickable = true
            setPadding(60, 40, 60, 40)
            setOnClickListener { text = "VERIFIED"; status.text = "Accessibility click received; waiting for verifier…" }
        }
        root.addView(status, LinearLayout.LayoutParams(-1, 0, 1f)); root.addView(target, LinearLayout.LayoutParams(-2, -2)); setContentView(root)
        waitForAgentService(0)
    }

    private fun waitForAgentService(attempt: Int) {
        if (UcoaAccessibilityService.instance != null) { startAgent(); return }
        if (attempt >= 30) { status.text = "UCOA_REAL_SMOKE_FAILED: accessibility service unavailable"; return }
        main.postDelayed({ waitForAgentService(attempt + 1) }, 400)
    }

    private fun startAgent() {
        val brain = AgentBrainClient(this)
        val loop = UniversalAgentLoop(brain)
        status.text = "UCOA smoke: observing screenshot…"
        loop.start("Press the visible CONTINUE button. Stop only after the screen changes to VERIFIED.", object : UniversalAgentLoop.Listener {
            override fun onEvent(text: String) {
                runOnUiThread {
                    status.text = text.take(500)
                    if (text.contains("الرؤية[huggingface-", true) || text.contains("الرؤية[huggingface_", true)) visionSeen = true
                    if (text.contains("التحقق: نجح", true)) verificationSeen = true
                }
            }
            override fun onFinished(success: Boolean) {
                runOnUiThread {
                    if (success && visionSeen && verificationSeen && target.text.toString() == "VERIFIED") {
                        status.text = "UCOA_REAL_SMOKE_OK"
                    } else {
                        status.text = "UCOA_REAL_SMOKE_FAILED: success=$success vision=$visionSeen verify=$verificationSeen state=${target.text}"
                    }
                }
            }
        })
    }
}
