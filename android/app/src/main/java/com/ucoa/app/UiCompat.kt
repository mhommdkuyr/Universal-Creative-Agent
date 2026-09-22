package com.ucoa.app

import android.widget.TextView

/** Small compatibility shims for the programmatic RTL UI. */
var TextView.hintTextColor: Int
    get() = currentTextColor
    set(value) { setHintTextColor(value) }

fun MainActivity.rounded(color: Int): android.graphics.drawable.GradientDrawable =
    android.graphics.drawable.GradientDrawable().apply { setColor(color); cornerRadius = 20f }
