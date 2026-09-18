package com.ucoa.app

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView

/**
 * Always-on-top execution surface owned by UCOA's AccessibilityService.
 *
 * This is intentionally rendered by UCOA itself (TYPE_ACCESSIBILITY_OVERLAY),
 * so the user can see the live execution state even while another app is in
 * the foreground. It does not receive touch input.
 */
class UcoaLiveExecutionOverlay(private val context: Context) {
    private val handler = Handler(Looper.getMainLooper())
    private val windowManager = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private var root: LinearLayout? = null
    private var attached = false
    private lateinit var title: TextView
    private lateinit var task: TextView
    private lateinit var phase: TextView
    private lateinit var evidence: TextView
    private lateinit var foreground: TextView
    private lateinit var detail: TextView

    fun start(commandId: String, taskText: String) {
        handler.post {
            removeInternal()
            val box = LinearLayout(context).apply {
                orientation = LinearLayout.VERTICAL
                layoutDirection = View.LAYOUT_DIRECTION_RTL
                setPadding(20, 16, 20, 16)
                background = panelBackground(Color.argb(242, 16, 18, 25))
                elevation = 12f
            }

            title = label("UCOA • التنفيذ الحي", 16f, Color.WHITE, true)
            task = label("", 12f, Color.rgb(224, 226, 235), false)
            phase = label("المرحلة: تهيئة المهمة", 12f, Color.rgb(196, 188, 255), true)
            evidence = label("الإثبات: UCOA يراقب قبل/بعد التنفيذ", 12f, Color.rgb(176, 210, 255), false)
            foreground = label("التطبيق الأمامي: —", 11f, Color.rgb(183, 187, 199), false)
            detail = label("المعرف: ${commandId.take(16)}", 10f, Color.rgb(138, 143, 156), false)

            box.addView(title)
            box.addView(task, lp(0, 8))
            box.addView(phase, lp(0, 4))
            box.addView(evidence, lp(0, 4))
            box.addView(foreground, lp(0, 4))
            box.addView(detail, lp(0, 2))
            root = box

            val params = WindowManager.LayoutParams(
                WindowManager.LayoutParams.MATCH_PARENT,
                WindowManager.LayoutParams.WRAP_CONTENT,
                WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                    WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                    WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
                android.graphics.PixelFormat.TRANSLUCENT
            ).apply {
                gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
                x = 0
                y = 18
            }

            try {
                windowManager.addView(box, params)
                attached = true
                task.text = "المهمة: ${taskText.replace("\n", " ").take(180)}"
            } catch (e: Exception) {
                attached = false
                root = null
                UcoaDiagnostics.log("LIVE_OVERLAY", "تعذر إظهار واجهة التنفيذ الحي", "${e.javaClass.simpleName}: ${e.message}")
            }
        }
    }

    fun update(
        step: Int,
        maxSteps: Int,
        phaseText: String,
        action: String,
        verified: Boolean? = null,
        foregroundPackage: String? = null,
        note: String? = null
    ) {
        handler.post {
            if (!attached) return@post
            phase.text = "المرحلة: $phaseText • الخطوة ${step.coerceAtLeast(0)} / $maxSteps • $action"
            evidence.text = when (verified) {
                true -> "الإثبات: ✓ تم التحقق من الحالة بعد التنفيذ بواسطة UCOA"
                false -> "الإثبات: ✗ لم يثبت تحقق الحالة — UCOA سيحاول الإصلاح/التوقف"
                null -> "الإثبات: جارٍ الالتقاط والتحقق عبر UCOA"
            }
            foreground.text = "التطبيق الأمامي: ${foregroundPackage ?: "جاري الرصد"}"
            if (!note.isNullOrBlank()) detail.text = note.take(220)
            root?.background = panelBackground(
                when (verified) {
                    true -> Color.argb(242, 10, 35, 24)
                    false -> Color.argb(242, 48, 18, 20)
                    null -> Color.argb(242, 16, 18, 25)
                }
            )
        }
    }

    fun finish(success: Boolean, message: String) {
        handler.post {
            if (!attached) return@post
            phase.text = if (success) "المرحلة: اكتملت المهمة" else "المرحلة: توقفت المهمة"
            evidence.text = if (success) {
                "الإثبات النهائي: ✓ UCOA أثبت التنفيذ والتحقق"
            } else {
                "الإثبات النهائي: ✗ UCOA لم يثبت اكتمال المهمة"
            }
            detail.text = message.take(220)
            foreground.text = "التطبيق الأمامي عند النهاية: ${UcoaAccessibilityService.instance?.foregroundPackageName() ?: "—"}"
            root?.background = panelBackground(if (success) Color.argb(245, 10, 43, 28) else Color.argb(245, 55, 20, 24))
            handler.postDelayed({ removeInternal() }, 5500L)
        }
    }

    fun remove() {
        handler.post { removeInternal() }
    }

    private fun removeInternal() {
        if (!attached) return
        runCatching { root?.let(windowManager::removeView) }
        attached = false
        root = null
    }

    private fun label(textValue: String, size: Float, color: Int, bold: Boolean): TextView =
        TextView(context).apply {
            text = textValue
            textSize = size
            setTextColor(color)
            typeface = if (bold) Typeface.DEFAULT_BOLD else Typeface.DEFAULT
            gravity = Gravity.RIGHT
        }

    private fun lp(top: Int, bottom: Int): LinearLayout.LayoutParams =
        LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        ).apply {
            setMargins(0, top, 0, bottom)
        }

    private fun panelBackground(color: Int) = GradientDrawable().apply {
        setColor(color)
        cornerRadius = 22f
        setStroke(1, Color.argb(100, 255, 255, 255))
    }
}
