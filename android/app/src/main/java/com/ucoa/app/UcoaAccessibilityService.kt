package com.ucoa.app

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Path
import android.os.Bundle
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject

class UcoaAccessibilityService : AccessibilityService() {
    companion object { var instance: UcoaAccessibilityService? = null }
    override fun onServiceConnected() { super.onServiceConnected(); instance=this }
    override fun onDestroy() { instance=null; super.onDestroy() }
    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit
    override fun onInterrupt() = Unit

    fun findText(text: String): AccessibilityNodeInfo? = windows.mapNotNull { it.root }.asSequence()
        .flatMap { it.findAccessibilityNodeInfosByText(text).asSequence() }.firstOrNull()
    fun clickText(text: String): Boolean = findText(text)?.performAction(AccessibilityNodeInfo.ACTION_CLICK) == true
    fun typeText(text: String): Boolean {
        val node=windows.mapNotNull { it.root }.asSequence().mapNotNull { it.findFocus(AccessibilityNodeInfo.FOCUS_INPUT) }.firstOrNull() ?: return false
        return node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,text) })
    }
    fun back()=performGlobalAction(GLOBAL_ACTION_BACK)
    fun home()=performGlobalAction(GLOBAL_ACTION_HOME)
    fun tap(x:Float,y:Float)=gesture(x,y,x,y,1)
    fun longPress(x:Float,y:Float,d:Long=700)=gesture(x,y,x,y,d)
    fun swipe(x1:Float,y1:Float,x2:Float,y2:Float,d:Long=500)=gesture(x1,y1,x2,y2,d)

    fun openApp(pkg:String):Boolean=try {
        val i=packageManager.getLaunchIntentForPackage(pkg) ?: return false
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK); startActivity(i); true
    } catch(_:Exception){false}

    fun openAppByName(query:String):Boolean {
        val q=query.trim().lowercase()
        val pm=packageManager
        val candidates=pm.getInstalledApplications(0)
            .filter { !it.packageName.equals(packageName, true) }
            .mapNotNull { app ->
                val label=pm.getApplicationLabel(app)?.toString() ?: return@mapNotNull null
                if (label.lowercase().contains(q) || app.packageName.lowercase().contains(q)) app else null
            }
            .sortedBy { pm.getApplicationLabel(it)?.toString()?.length ?: 999 }
        return candidates.firstOrNull()?.let { openApp(it.packageName) } ?: false
    }

    fun observeUi(maxNodes:Int=120):String {
        val result=JSONArray()
        val roots=windows.mapNotNull { it.root }
        fun walk(node:AccessibilityNodeInfo?) {
            if (node==null || result.length()>=maxNodes) return
            val b=android.graphics.Rect(); node.getBoundsInScreen(b)
            result.put(JSONObject().apply {
                put("class", node.className ?: "")
                put("text", node.text ?: "")
                put("description", node.contentDescription ?: "")
                put("clickable", node.isClickable)
                put("enabled", node.isEnabled)
                put("focused", node.isFocused)
                put("bounds", JSONObject().apply { put("left",b.left);put("top",b.top);put("right",b.right);put("bottom",b.bottom) })
            })
            for (i in 0 until node.childCount) walk(node.getChild(i))
        }
        roots.forEach { walk(it) }
        return result.toString()
    }

    private fun gesture(x1:Float,y1:Float,x2:Float,y2:Float,d:Long):Boolean {
        val p=Path().apply { moveTo(x1,y1); lineTo(x2,y2) }
        val s=GestureDescription.StrokeDescription(p,0,d.coerceAtLeast(1))
        return dispatchGesture(GestureDescription.Builder().addStroke(s).build(),null,null)
    }
}
