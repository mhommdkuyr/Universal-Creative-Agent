package com.ucoa.app

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Path
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.util.Base64
import android.view.Display
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream

class UcoaAccessibilityService : AccessibilityService() {
    companion object { @Volatile var instance: UcoaAccessibilityService? = null }
    @Volatile private var lastForegroundPackage: String? = null

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        UcoaDiagnostics.init(this)
        UcoaDiagnostics.log("ACCESSIBILITY", "خدمة الوصول اتصلت فعليًا", "package=$packageName")
    }

    override fun onDestroy() {
        UcoaDiagnostics.log("ACCESSIBILITY", "خدمة الوصول انقطعت")
        instance = null
        super.onDestroy()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        event?.packageName?.toString()?.takeIf { it.isNotBlank() }?.let {
            if (it != lastForegroundPackage) {
                lastForegroundPackage = it
                UcoaDiagnostics.log("OBSERVE", "تغير التطبيق الأمامي", "package=$it event=${event.eventType}")
            }
        }
    }

    override fun onInterrupt() { UcoaDiagnostics.log("ACCESSIBILITY", "أرسل النظام interrupt للخدمة") }

    fun foregroundPackageName(): String? = lastForegroundPackage ?: windows.asSequence().mapNotNull { it.root?.packageName?.toString() }.firstOrNull()
    fun findText(text: String): AccessibilityNodeInfo? = windows.mapNotNull { it.root }.asSequence().flatMap { it.findAccessibilityNodeInfosByText(text).asSequence() }.firstOrNull()
    fun clickText(text: String): Boolean = findText(text)?.let(::clickNode) == true
    fun clickAnyText(texts: List<String>): Boolean {
        val wanted = texts.map(::normalize).filter { it.isNotBlank() }
        val nodes = allNodes()
        nodes.firstOrNull { normalize(nodeText(it)) in wanted }?.let { if (clickNode(it)) return true }
        nodes.firstOrNull { n -> val v = normalize(nodeText(n)); v.isNotBlank() && wanted.any { v.contains(it) } }?.let { if (clickNode(it)) return true }
        nodes.firstOrNull { n -> val v = normalize(nodeText(n)); v.isNotBlank() && wanted.any { v.contains(it) } }?.let { n -> val b = android.graphics.Rect(); n.getBoundsInScreen(b); if (b.width() > 2 && b.height() > 2) return tap(b.centerX().toFloat(), b.centerY().toFloat()) }
        return false
    }
    fun typeText(text: String): Boolean { val node = allNodes().firstOrNull { it.isEditable && it.isFocused } ?: allNodes().firstOrNull { it.isEditable } ?: windows.mapNotNull { it.root }.asSequence().mapNotNull { it.findFocus(AccessibilityNodeInfo.FOCUS_INPUT) }.firstOrNull() ?: return false; return setNodeText(node, text) }
    fun typeIntoAny(hints: List<String>, text: String): Boolean { val wanted = hints.map(::normalize).filter { it.isNotBlank() }; val candidates = allNodes().filter { it.isEditable || it.className?.toString()?.contains("EditText", true) == true }; val hinted = candidates.firstOrNull { n -> val v = normalize(nodeText(n)) + " " + normalize(n.hintText?.toString() ?: "") + " " + normalize(n.contentDescription?.toString() ?: ""); v.isNotBlank() && wanted.any { v.contains(it) } }; return setNodeText(hinted ?: candidates.firstOrNull() ?: return false, text) }
    fun back() = performGlobalAction(GLOBAL_ACTION_BACK)
    fun home() = performGlobalAction(GLOBAL_ACTION_HOME)
    fun tap(x: Float, y: Float) = gesture(x, y, x, y, 1)
    fun longPress(x: Float, y: Float, d: Long = 700) = gesture(x, y, x, y, d)
    fun swipe(x1: Float, y1: Float, x2: Float, y2: Float, d: Long = 500) = gesture(x1, y1, x2, y2, d)

    fun packageForName(query: String): String? {
        val q = normalize(query)
        val known = mapOf(
            "capcut" to "com.lemon.lvoverseas", "كاب كات" to "com.lemon.lvoverseas", "كابكات" to "com.lemon.lvoverseas",
            "youtube" to "com.google.android.youtube", "يوتيوب" to "com.google.android.youtube",
            "canva" to "com.canva.editor", "كانفا" to "com.canva.editor",
            "chrome" to "com.android.chrome", "كروم" to "com.android.chrome",
            "instagram" to "com.instagram.android", "انستجرام" to "com.instagram.android", "انستغرام" to "com.instagram.android",
            "whatsapp" to "com.whatsapp", "واتساب" to "com.whatsapp",
            "telegram" to "org.telegram.messenger", "تليجرام" to "org.telegram.messenger",
            "settings" to "com.android.settings", "الإعدادات" to "com.android.settings", "اعدادات" to "com.android.settings", "الضبط" to "com.android.settings"
        )
        return known.entries.firstOrNull { q.contains(normalize(it.key)) }?.value
    }

    fun openApp(pkg: String): Boolean = try {
        val intent = packageManager.getLaunchIntentForPackage(pkg)
        if (intent == null) {
            UcoaDiagnostics.log("EXECUTOR", "لم نجد launch intent", "package=$pkg")
            return false
        }
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        startActivity(intent)
        UcoaDiagnostics.log("EXECUTOR", "تم استدعاء startActivity", "package=$pkg")
        true
    } catch (e: Exception) {
        UcoaDiagnostics.log("EXECUTOR", "استثناء أثناء فتح التطبيق", "package=$pkg error=${e.javaClass.simpleName}: ${e.message}")
        false
    }

    fun openAppByName(query: String): Boolean {
        val q = normalize(query)
        val direct = packageForName(query)
        if (direct != null && openApp(direct)) return true
        val pm = packageManager
        val candidates = pm.getInstalledApplications(0)
            .filter { !it.packageName.equals(packageName, true) }
            .mapNotNull { app ->
                val label = pm.getApplicationLabel(app)?.toString() ?: return@mapNotNull null
                if (normalize(label).contains(q) || normalize(app.packageName).contains(q)) app else null
            }
            .sortedBy { pm.getApplicationLabel(it)?.toString()?.length ?: 999 }
        val fallback = candidates.firstOrNull()?.packageName
        UcoaDiagnostics.log("EXECUTOR", "نتيجة مطابقة اسم التطبيق", "query=$query mapped=$direct fallback=$fallback")
        return fallback?.let { openApp(it) } ?: false
    }

    fun installedAppLabels(): List<String> = packageManager.getInstalledApplications(0).filter { it.packageName != packageName }.mapNotNull { packageManager.getApplicationLabel(it)?.toString() }.distinct().sorted().take(250)
    fun openUrl(url: String): Boolean = try { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }); UcoaDiagnostics.log("EXECUTOR", "فتح URL", url.take(240)); true } catch (e: Exception) { UcoaDiagnostics.log("EXECUTOR", "فشل فتح URL", e.message ?: e.javaClass.simpleName); false }
    fun shareAttachment(uriString: String, packageNameTarget: String? = null): Boolean = try { val uri = Uri.parse(uriString); val intent = Intent(Intent.ACTION_SEND).apply { type = contentResolver.getType(uri) ?: "*/*"; putExtra(Intent.EXTRA_STREAM, uri); addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION); packageNameTarget?.takeIf { it.isNotBlank() }?.let(::setPackage) }; startActivity(intent); UcoaDiagnostics.log("EXECUTOR", "مشاركة مرفق", "target=$packageNameTarget"); true } catch (e: Exception) { UcoaDiagnostics.log("EXECUTOR", "فشل مشاركة مرفق", e.message ?: e.javaClass.simpleName); false }
    fun observeUi(maxNodes: Int = 160): String { val result = JSONArray(); allNodes(maxNodes).forEach { node -> val b = android.graphics.Rect(); node.getBoundsInScreen(b); result.put(JSONObject().apply { put("class", node.className ?: ""); put("text", node.text ?: ""); put("hint", node.hintText ?: ""); put("description", node.contentDescription ?: ""); put("clickable", node.isClickable); put("editable", node.isEditable); put("enabled", node.isEnabled); put("focused", node.isFocused); put("bounds", JSONObject().apply { put("left", b.left); put("top", b.top); put("right", b.right); put("bottom", b.bottom) }) }) }; return result.toString() }
    fun captureScreenshotBase64(callback: (String?) -> Unit) { if (Build.VERSION.SDK_INT < 30) { callback(null); return }; try { takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, object : TakeScreenshotCallback { override fun onSuccess(result: ScreenshotResult) { try { val hw = result.hardwareBuffer; val bitmap = Bitmap.wrapHardwareBuffer(hw, result.colorSpace)?.copy(Bitmap.Config.ARGB_8888, false); hw.close(); if (bitmap == null) { callback(null); return }; val out = ByteArrayOutputStream(); bitmap.compress(Bitmap.CompressFormat.JPEG, 72, out); bitmap.recycle(); callback(Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)) } catch (_: Exception) { runCatching { result.hardwareBuffer.close() }; callback(null) } }; override fun onFailure(errorCode: Int) { callback(null) } }) } catch (_: Exception) { callback(null) } }
    private fun allNodes(max: Int = 400): List<AccessibilityNodeInfo> { val result = mutableListOf<AccessibilityNodeInfo>(); fun walk(n: AccessibilityNodeInfo?) { if (n == null || result.size >= max) return; result += n; for (i in 0 until n.childCount) walk(n.getChild(i)) }; windows.mapNotNull { it.root }.forEach(::walk); return result }
    private fun nodeText(n: AccessibilityNodeInfo): String = listOfNotNull(n.text?.toString(), n.hintText?.toString(), n.contentDescription?.toString()).joinToString(" ")
    private fun normalize(v: String): String = v.trim().lowercase().replace("ـ", "").replace(Regex("\\s+"), " ")
    private fun clickNode(n: AccessibilityNodeInfo): Boolean { if (n.isClickable && n.isEnabled) return n.performAction(AccessibilityNodeInfo.ACTION_CLICK); var p = n.parent; while (p != null) { if (p.isClickable && p.isEnabled) return p.performAction(AccessibilityNodeInfo.ACTION_CLICK); p = p.parent }; return false }
    private fun setNodeText(n: AccessibilityNodeInfo, text: String): Boolean { if (!n.isEnabled) return false; n.performAction(AccessibilityNodeInfo.ACTION_FOCUS); return n.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text) }) }
    private fun gesture(x1: Float, y1: Float, x2: Float, y2: Float, d: Long): Boolean { val p = Path().apply { moveTo(x1, y1); lineTo(x2, y2) }; val s = GestureDescription.StrokeDescription(p, 0, d.coerceAtLeast(1)); return dispatchGesture(GestureDescription.Builder().addStroke(s).build(), null, null) }
}
