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
    companion object { var instance: UcoaAccessibilityService? = null }
    override fun onServiceConnected() { super.onServiceConnected(); instance = this }
    override fun onDestroy() { instance = null; super.onDestroy() }
    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit
    override fun onInterrupt() = Unit

    fun findText(text: String): AccessibilityNodeInfo? = windows.mapNotNull { it.root }.asSequence().flatMap { it.findAccessibilityNodeInfosByText(text).asSequence() }.firstOrNull()
    fun clickText(text: String): Boolean = findText(text)?.let(::clickNode) == true
    fun clickAnyText(texts: List<String>): Boolean {
        val wanted = texts.map(::normalize).filter { it.isNotBlank() }; val nodes = allNodes()
        nodes.firstOrNull { normalize(nodeText(it)) in wanted }?.let { if (clickNode(it)) return true }
        nodes.firstOrNull { n -> val v = normalize(nodeText(n)); v.isNotBlank() && wanted.any { v.contains(it) } }?.let { if (clickNode(it)) return true }
        return false
    }
    fun typeText(text: String): Boolean {
        val node = allNodes().firstOrNull { it.isEditable && it.isFocused } ?: allNodes().firstOrNull { it.isEditable }
            ?: windows.mapNotNull { it.root }.asSequence().mapNotNull { it.findFocus(AccessibilityNodeInfo.FOCUS_INPUT) }.firstOrNull() ?: return false
        return setNodeText(node, text)
    }
    fun typeIntoAny(hints: List<String>, text: String): Boolean {
        val wanted = hints.map(::normalize).filter { it.isNotBlank() }
        val candidates = allNodes().filter { it.isEditable || it.className?.toString()?.contains("EditText", true) == true }
        val hinted = candidates.firstOrNull { n -> val v = normalize(nodeText(n)) + " " + normalize(n.hintText?.toString() ?: "") + " " + normalize(n.contentDescription?.toString() ?: ""); v.isNotBlank() && wanted.any { v.contains(it) } }
        return setNodeText(hinted ?: candidates.firstOrNull() ?: return false, text)
    }
    fun back() = performGlobalAction(GLOBAL_ACTION_BACK)
    fun home() = performGlobalAction(GLOBAL_ACTION_HOME)
    fun tap(x: Float, y: Float) = gesture(x, y, x, y, 1)
    fun longPress(x: Float, y: Float, d: Long = 700) = gesture(x, y, x, y, d)
    fun swipe(x1: Float, y1: Float, x2: Float, y2: Float, d: Long = 500) = gesture(x1, y1, x2, y2, d)
    fun openApp(pkg: String): Boolean = try { packageManager.getLaunchIntentForPackage(pkg)?.apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }?.also(::startActivity) != null } catch (_: Exception) { false }
    fun openAppByName(query: String): Boolean {
        val q = query.trim().lowercase(); val pm = packageManager
        val candidates = pm.getInstalledApplications(0).filter { !it.packageName.equals(packageName, true) }.mapNotNull { app -> val label = pm.getApplicationLabel(app)?.toString() ?: return@mapNotNull null; if (label.lowercase().contains(q) || app.packageName.lowercase().contains(q)) app else null }.sortedBy { pm.getApplicationLabel(it)?.toString()?.length ?: 999 }
        return candidates.firstOrNull()?.let { openApp(it.packageName) } ?: false
    }
    fun installedAppLabels(): List<String> = packageManager.getInstalledApplications(0).filter { it.packageName != packageName }.mapNotNull { packageManager.getApplicationLabel(it)?.toString() }.distinct().sorted().take(250)
    fun openUrl(url: String): Boolean = try { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }); true } catch (_: Exception) { false }

    fun shareAttachment(uriString: String, packageNameTarget: String? = null): Boolean = try {
        val uri = Uri.parse(uriString)
        val intent = Intent(Intent.ACTION_SEND).apply { type = contentResolver.getType(uri) ?: "*/*"; putExtra(Intent.EXTRA_STREAM, uri); addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION); packageNameTarget?.takeIf { it.isNotBlank() }?.let(::setPackage) }
        startActivity(intent); true
    } catch (_: Exception) { false }

    fun observeUi(maxNodes: Int = 160): String {
        val result = JSONArray(); allNodes(maxNodes).forEach { node -> val b = android.graphics.Rect(); node.getBoundsInScreen(b); result.put(JSONObject().apply {
            put("class", node.className ?: ""); put("text", node.text ?: ""); put("hint", node.hintText ?: ""); put("description", node.contentDescription ?: "")
            put("clickable", node.isClickable); put("editable", node.isEditable); put("enabled", node.isEnabled); put("focused", node.isFocused)
            put("bounds", JSONObject().apply { put("left", b.left); put("top", b.top); put("right", b.right); put("bottom", b.bottom) })
        }) }
        return result.toString()
    }

    fun captureScreenshotBase64(callback: (String?) -> Unit) {
        if (Build.VERSION.SDK_INT < 30) { callback(null); return }
        try {
            takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, object : TakeScreenshotCallback {
                override fun onSuccess(result: ScreenshotResult) {
                    try {
                        val hw = result.hardwareBuffer
                        val bitmap = Bitmap.wrapHardwareBuffer(hw, result.colorSpace)?.copy(Bitmap.Config.ARGB_8888, false)
                        hw.close()
                        if (bitmap == null) { callback(null); return }
                        val out = ByteArrayOutputStream(); bitmap.compress(Bitmap.CompressFormat.JPEG, 62, out); bitmap.recycle(); callback(Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP))
                    } catch (_: Exception) { runCatching { result.hardwareBuffer.close() }; callback(null) }
                }
                override fun onFailure(errorCode: Int) { callback(null) }
            })
        } catch (_: Exception) { callback(null) }
    }

    private fun allNodes(max: Int = 400): List<AccessibilityNodeInfo> { val result = mutableListOf<AccessibilityNodeInfo>(); fun walk(n: AccessibilityNodeInfo?) { if (n == null || result.size >= max) return; result += n; for (i in 0 until n.childCount) walk(n.getChild(i)) }; windows.mapNotNull { it.root }.forEach(::walk); return result }
    private fun nodeText(n: AccessibilityNodeInfo): String = listOfNotNull(n.text?.toString(), n.hintText?.toString(), n.contentDescription?.toString()).joinToString(" ")
    private fun normalize(v: String): String = v.trim().lowercase().replace("ـ", "").replace(Regex("\\s+"), " ")
    private fun clickNode(n: AccessibilityNodeInfo): Boolean { if (n.isClickable && n.isEnabled) return n.performAction(AccessibilityNodeInfo.ACTION_CLICK); var p = n.parent; while (p != null) { if (p.isClickable && p.isEnabled) return p.performAction(AccessibilityNodeInfo.ACTION_CLICK); p = p.parent }; return false }
    private fun setNodeText(n: AccessibilityNodeInfo, text: String): Boolean { if (!n.isEnabled) return false; n.performAction(AccessibilityNodeInfo.ACTION_FOCUS); return n.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text) }) }
    private fun gesture(x1: Float, y1: Float, x2: Float, y2: Float, d: Long): Boolean { val p = Path().apply { moveTo(x1, y1); lineTo(x2, y2) }; val s = GestureDescription.StrokeDescription(p, 0, d.coerceAtLeast(1)); return dispatchGesture(GestureDescription.Builder().addStroke(s).build(), null, null) }
}
