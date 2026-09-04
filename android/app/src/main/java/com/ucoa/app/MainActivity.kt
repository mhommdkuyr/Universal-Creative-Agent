package com.ucoa.app

import android.app.Activity
import android.os.Bundle
import android.provider.Settings
import android.content.Intent
import android.graphics.Color
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView

class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val input=EditText(this).apply { hint="اكتب المهمة التي تريد من الوكيل تنفيذها"; minLines=4; setTextColor(Color.BLACK) }
        val target=EditText(this).apply { hint="التطبيق/الهدف: CapCut / Canva / Chrome / VS Code"; setTextColor(Color.BLACK) }
        val enable=Button(this).apply { text="فتح إعدادات الوصول" }
        val run=Button(this).apply { text="بدء المهمة" }
        val status=TextView(this).apply { text="Universal Creative Agent v0.3 — جاهز"; setPadding(0,24,0,24) }
        enable.setOnClickListener { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
        run.setOnClickListener { status.text="تمت جدولة المهمة:\n${input.text}\nالهدف: ${target.text}\nطبقة Agent Core جاهزة لاستقبال الخطة." }
        val root=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(32,48,32,32) }
        listOf(input,target,enable,run,status).forEach { root.addView(it, ViewGroup.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT)) }
        setContentView(root)
    }
}
