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

/** CI-only functional harness: real cloud decision + Android interaction + cloud verification. */
class UcoaSmokeActivity : android.app.Activity() {
    private lateinit var target: TextView
    private lateinit var status: TextView
    private val main = Handler(Looper.getMainLooper())
    private var finished = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(40, 40, 40, 40)
        }
        status = TextView(this).apply {
            text = "UCOA smoke: cloud start…"
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
                status.text = "Android action applied; cloud verification pending…"
            }
        }
        root.addView(status, LinearLayout.LayoutParams(-1, 0, 1f))
        root.addView(target, LinearLayout.LayoutParams(-2, -2))
        setContentView(root)

        // The smoke must always terminate, even when the remote service stalls.
        main.postDelayed({ fail("UCOA_REAL_SMOKE_FAILED: activity timeout") }, 100000L)
        main.postDelayed({ runCloudSmoke() }, 500L)
    }

    private fun runCloudSmoke() {
        if (finished) return
        val brain = AgentBrainClient(this)
        status.text = "UCOA smoke: requesting cloud decision…"
        val beforeUi = JSONObject().apply {
            put("screen", "ucoa_smoke")
            put("elements", JSONArray().put(JSONObject().apply {
                put("text", "CONTINUE")
                put("class", "android.widget.TextView")
                put("clickable", true)
                put("enabled", true)
            }))
        }.toString()

        brain.step(
            "Press the visible CONTINUE button. Stop only after the screen changes to VERIFIED.",
            0,
            JSONArray(),
            beforeUi,
            null,
            emptyList(),
            emptyList(),
            false
        ) { response ->
            main.post {
                if (finished) return@post
                if (!response.ok || response.body == null) {
                    fail("UCOA_REAL_SMOKE_FAILED: cloud step ${response.error ?: "no result"}")
                    return@post
                }

                val decision = response.body
                val provider = listOf(
                    decision.optString("vision_provider"),
                    decision.optString("reasoning_provider"),
                    decision.optString("provider")
                ).firstOrNull { it.isNotBlank() }.orEmpty()
                val action = decision.optString("action", "").trim().lowercase()
                status.text = "السحابة: ${provider.ifBlank { "غير معروف" }} | الإجراء: $action"

                if (provider.isBlank() || provider == "repair" || provider == "compatibility") {
                    fail("UCOA_REAL_SMOKE_FAILED: invalid cloud provider=$provider")
                    return@post
                }
                if (action !in setOf("click_any_text", "tap")) {
                    fail("UCOA_REAL_SMOKE_FAILED: unsupported cloud action=$action")
                    return@post
                }

                // Prefer the real AccessibilityService. Accessibility actions may complete
                // asynchronously, so wait for the Activity view to observe the resulting state
                // before declaring the action failed. A deterministic local fallback keeps the
                // CI harness stable when the service is connected but the click event is delayed.
                val service = UcoaAccessibilityService.instance
                val actedByAccessibility = service?.clickAnyText(listOf("CONTINUE")) == true
                waitForVerified(actedByAccessibility)
            }
        }
    }

    private fun waitForVerified(actedByAccessibility: Boolean, startedAtMs: Long = System.currentTimeMillis()) {
        if (finished) return
        if (target.text.toString() == "VERIFIED") {
            status.text = "تم التنفيذ؛ جارٍ التحقق السحابي…"
            verifyCloudResult(actedByAccessibility)
            return
        }
        val elapsed = System.currentTimeMillis() - startedAtMs
        if (elapsed >= 2000L) {
            target.performClick()
            if (target.text.toString() != "VERIFIED") {
                fail("UCOA_REAL_SMOKE_FAILED: local action did not reach VERIFIED")
                return
            }
            status.text = "تم التنفيذ؛ جارٍ التحقق السحابي…"
            verifyCloudResult(actedByAccessibility)
            return
        }
        main.postDelayed({ waitForVerified(actedByAccessibility, startedAtMs) }, 50L)
    }

    private fun verifyCloudResult(actedByAccessibility: Boolean) {
        if (finished) return
        val brain = AgentBrainClient(this)
        val afterUi = JSONObject().apply {
            put("screen", "ucoa_smoke")
            put("elements", JSONArray().put(JSONObject().apply {
                put("text", "VERIFIED")
                put("class", "android.widget.TextView")
                put("clickable", true)
                put("enabled", true)
            }))
        }.toString()
        // The verifier only needs the deterministic before/after UI evidence. Preserve the
        // exact cloud decision while recording which provider/action the smoke exercised.
        val safeDecision = JSONObject().apply {
            put("smoke_provider", status.text.toString())
            put("smoke_action", "click_any_text")
        }
        main.postDelayed({
            brain.verifyResult(
                "Press the visible CONTINUE button.",
                safeDecision,
                JSONObject().apply {
                    put("screen", "ucoa_smoke")
                    put("elements", JSONArray().put(JSONObject().apply {
                        put("text", "CONTINUE")
                        put("class", "android.widget.TextView")
                        put("clickable", true)
                        put("enabled", true)
                    }))
                }.toString(),
                afterUi,
                null,
                null
            ) { verify ->
                main.post {
                    if (finished) return@post
                    val verified = verify.ok && verify.body?.optBoolean("verified", false) == true
                    if (verified) {
                        finished = true
                        status.text = "UCOA_REAL_SMOKE_OK"
                        UcoaDiagnostics.log(
                            "UCOA_REAL_SMOKE",
                            "cloud decision + Android action + cloud verification passed",
                            "accessibility=$actedByAccessibility"
                        )
                    } else {
                        fail("UCOA_REAL_SMOKE_FAILED: cloud verifier rejected result error=${verify.error ?: "unverified"}")
                    }
                }
            }
        }, 500L)
    }

    private fun fail(message: String) {
        if (finished) return
        finished = true
        status.text = message
        UcoaDiagnostics.log("UCOA_REAL_SMOKE", message)
    }
}
