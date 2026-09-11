package com.ucoa.app

import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject

/** CI-only functional harness: one real cloud vision decision + accessibility action + verifier. */
class UcoaSmokeActivity : android.app.Activity() {
    private lateinit var target: TextView
    private lateinit var status: TextView
    private val main = Handler(Looper.getMainLooper())
    private var visionProvider = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(40, 40, 40, 40)
        }
        status = TextView(this).apply {
            text = "UCOA smoke: starting…"
            textSize = 18f
            setTextColor(Color.DKGRAY)
            gravity = Gravity.CENTER
        }
        target = TextView(this).apply {
            text = "CONTINUE"
            textSize = 30f
            gravity = Gravity.CENTER
            setTextColor(Color.BLACK)
            setBackgroundColor(Color.LTGRAY)
            isClickable = true
            setPadding(60, 40, 60, 40)
            setOnClickListener {
                text = "VERIFIED"
                status.text = "Accessibility click received; waiting for verifier…"
            }
        }
        root.addView(status, LinearLayout.LayoutParams(-1, 0, 1f))
        root.addView(target, LinearLayout.LayoutParams(-2, -2))
        setContentView(root)
        waitForAgentService(0)
    }

    private fun waitForAgentService(attempt: Int) {
        if (UcoaAccessibilityService.instance != null) {
            runCloudVisionActVerify()
            return
        }
        if (attempt >= 30) {
            fail("UCOA_REAL_SMOKE_FAILED: accessibility service unavailable")
            return
        }
        main.postDelayed({ waitForAgentService(attempt + 1) }, 400)
    }

    private fun runCloudVisionActVerify() {
        val service = UcoaAccessibilityService.instance
        if (service == null) {
            fail("UCOA_REAL_SMOKE_FAILED: service disappeared")
            return
        }
        val brain = AgentBrainClient(this)
        status.text = "UCOA smoke: observing screenshot…"
        service.captureScreenshotBase64 { beforeScreenshot ->
            val beforeUi = service.observeUi(320)
            brain.step(
                "Press the visible CONTINUE button. Stop only after the screen changes to VERIFIED.",
                0,
                JSONArray(),
                beforeUi,
                beforeScreenshot,
                service.installedAppLabels(),
                emptyList(),
                false
            ) { response ->
                main.post {
                    if (!response.ok || response.body == null) {
                        fail("UCOA_REAL_SMOKE_FAILED: cloud step ${response.error ?: "no result"}")
                        return@post
                    }
                    val decision = response.body
                    visionProvider = decision.optString("vision_provider", "")
                    val action = decision.optString("action", "").trim().lowercase()
                    val params = decision.optJSONObject("params") ?: JSONObject()
                    status.text = "الرؤية: ${visionProvider.ifBlank { "غير معروف" }} | الإجراء: $action"
                    if (visionProvider.isBlank() || visionProvider == "repair" || visionProvider == "compatibility") {
                        fail("UCOA_REAL_SMOKE_FAILED: invalid vision provider=$visionProvider")
                        return@post
                    }
                    val executed = when (action) {
                        "click_any_text" -> {
                            val texts = mutableListOf<String>()
                            params.optJSONArray("texts")?.let { arr ->
                                for (i in 0 until arr.length()) texts += arr.optString(i)
                            }
                            if (texts.isEmpty()) params.optString("text").takeIf { it.isNotBlank() }?.let { texts += it }
                            service.clickAnyText(texts)
                        }
                        "tap" -> service.tap(params.optDouble("x").toFloat(), params.optDouble("y").toFloat())
                        else -> false
                    }
                    if (!executed) {
                        fail("UCOA_REAL_SMOKE_FAILED: cloud action not executable=$action")
                        return@post
                    }
                    status.text = "تم التنفيذ؛ جارٍ التحقق المستقل…"
                    main.postDelayed({
                        service.captureScreenshotBase64 { afterScreenshot ->
                            val afterUi = service.observeUi(320)
                            brain.verifyResult(
                                "Press the visible CONTINUE button.",
                                decision,
                                beforeUi,
                                afterUi,
                                beforeScreenshot,
                                afterScreenshot
                            ) { verify ->
                                main.post {
                                    val verified = verify.ok && verify.body?.optBoolean("verified", false) == true
                                    if (verified && target.text.toString() == "VERIFIED") {
                                        status.text = "UCOA_REAL_SMOKE_OK"
                                        UcoaDiagnostics.log("UCOA_REAL_SMOKE", "cloud vision + accessibility + verification passed", "vision=$visionProvider action=$action")
                                    } else {
                                        fail("UCOA_REAL_SMOKE_FAILED: verified=$verified vision=$visionProvider state=${target.text}")
                                    }
                                }
                            }
                        }
                    }, 700L)
                }
            }
        }
    }

    private fun fail(message: String) {
        status.text = message
        UcoaDiagnostics.log("UCOA_REAL_SMOKE", message)
    }
}
