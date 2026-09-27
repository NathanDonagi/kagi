package com.example.kagi.ui

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.kagi.ui.theme.LocalKagi

// The desktop app's Qt stylesheet, as composables.

@Composable
fun Brand() {
    Text(
        "KAGI", Modifier.fillMaxWidth(), color = LocalKagi.current.muted, fontSize = 13.sp,
        letterSpacing = 3.sp, textAlign = TextAlign.Center,
    )
    Spacer(Modifier.height(40.dp))
}

@Composable
fun Title(text: String, color: Color = LocalKagi.current.ink) {
    Text(
        text, Modifier.fillMaxWidth(), color = color, fontSize = 28.sp, fontWeight = FontWeight.SemiBold,
        textAlign = TextAlign.Center, lineHeight = 34.sp,
    )
}

@Composable
fun Muted(text: String, size: TextUnit = 16.sp, modifier: Modifier = Modifier) {
    Text(
        text, modifier.fillMaxWidth(), color = LocalKagi.current.muted, fontSize = size,
        textAlign = TextAlign.Center, lineHeight = size * 1.4f,
    )
}

@Composable
fun ErrorText(text: String) {
    Text(
        text, Modifier.fillMaxWidth().heightIn(min = 28.dp), color = LocalKagi.current.red, fontSize = 14.sp,
        textAlign = TextAlign.Center,
    )
}

@Composable
fun PrimaryButton(text: String, enabled: Boolean = true, onClick: () -> Unit) {
    val k = LocalKagi.current
    Box(
        Modifier.fillMaxWidth()
            .background(if (enabled) k.ink else k.muted, RoundedCornerShape(24.dp))
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 28.dp, vertical = 14.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, color = k.bg, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
fun TextButton(text: String, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Text(
        text, modifier.clickable(onClick = onClick).padding(8.dp),
        color = LocalKagi.current.muted, fontSize = 16.sp,
    )
}

/** QLineEdit: field background, 1px line border (ink when focused), 12 px corners. */
@Composable
fun Field(
    value: TextFieldValue,
    onChange: (TextFieldValue) -> Unit,
    placeholder: String,
    modifier: Modifier = Modifier,
    style: TextStyle = TextStyle(fontSize = 16.sp),
    keyboard: KeyboardOptions = KeyboardOptions.Default,
    actions: KeyboardActions = KeyboardActions.Default,
    visualTransformation: VisualTransformation = VisualTransformation.None,
) {
    val k = LocalKagi.current
    val interaction = remember { MutableInteractionSource() }
    val focused by interaction.collectIsFocusedAsState()
    val textStyle = style.copy(color = k.ink)
    BasicTextField(
        value, onChange, modifier.fillMaxWidth(), singleLine = true, textStyle = textStyle,
        keyboardOptions = keyboard, keyboardActions = actions, interactionSource = interaction,
        cursorBrush = SolidColor(k.ink), visualTransformation = visualTransformation,
        decorationBox = { inner ->
            Box(
                Modifier.fillMaxWidth()
                    .background(k.field, RoundedCornerShape(12.dp))
                    .border(1.dp, if (focused) k.ink else k.line, RoundedCornerShape(12.dp))
                    .padding(horizontal = 16.dp, vertical = 12.dp),
                contentAlignment = if (style.textAlign == TextAlign.Center) Alignment.Center else Alignment.CenterStart,
            ) {
                if (value.text.isEmpty()) Text(placeholder, style = textStyle.copy(color = k.muted))
                inner()
            }
        },
    )
}

val CodeStyle = TextStyle(
    fontFamily = FontFamily.Monospace, fontSize = 30.sp, fontWeight = FontWeight.SemiBold,
    textAlign = TextAlign.Center,
)

/** QFrame#card with key/value rows and hairline separators. */
@Composable
fun InfoCard(rows: List<Pair<String, String>>) {
    val k = LocalKagi.current
    Column(
        Modifier.fillMaxWidth()
            .background(k.field, RoundedCornerShape(16.dp))
            .border(1.dp, k.line, RoundedCornerShape(16.dp))
            .padding(horizontal = 24.dp, vertical = 8.dp)
    ) {
        rows.forEachIndexed { i, (key, value) ->
            if (i > 0) Box(Modifier.fillMaxWidth().height(1.dp).background(k.line))
            Row(
                Modifier.fillMaxWidth().padding(vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(key, color = k.muted, fontSize = 16.sp)
                Text(
                    value, Modifier.weight(1f), color = k.ink, fontSize = 18.sp, fontWeight = FontWeight.SemiBold,
                    textAlign = TextAlign.End,
                )
            }
        }
    }
}

@Composable
fun SwitchRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    val k = LocalKagi.current
    Row(
        Modifier.fillMaxWidth().clickable { onChange(!checked) }.padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, Modifier.weight(1f), color = k.ink, fontSize = 16.sp)
        Switch(
            checked, onChange,
            colors = SwitchDefaults.colors(
                checkedThumbColor = k.bg, checkedTrackColor = k.ink,
                uncheckedThumbColor = k.muted, uncheckedTrackColor = k.field, uncheckedBorderColor = k.line,
            ),
        )
    }
}

enum class IconMode { SPIN, OK, FAIL }

/** desktop_app.py's StatusIcon: an anti-aliased spinner, tick or cross, 88 px. */
@Composable
fun StatusIcon(mode: IconMode) {
    val k = LocalKagi.current
    val angle by rememberInfiniteTransition(label = "spin").animateFloat(
        0f, 360f, infiniteRepeatable(tween(1000, easing = LinearEasing)), label = "angle",
    )
    Canvas(Modifier.size(88.dp)) {
        val u = size.width / 88f             // the Qt version's coordinates are in an 88 box
        if (mode == IconMode.SPIN) {
            val stroke = 5 * u
            val topLeft = Offset(5 * u, 5 * u)
            val arcSize = Size(78 * u, 78 * u)
            drawArc(k.line, 0f, 360f, false, topLeft, arcSize, style = Stroke(stroke))
            drawArc(k.ink, angle, 80f, false, topLeft, arcSize, style = Stroke(stroke, cap = StrokeCap.Round))
            return@Canvas
        }
        drawCircle(if (mode == IconMode.OK) k.green else k.red, radius = 42 * u, center = Offset(44 * u, 44 * u))
        val path = Path().apply {
            if (mode == IconMode.OK) {
                moveTo(27 * u, 45 * u); lineTo(39 * u, 57 * u); lineTo(62 * u, 32 * u)
            } else {
                moveTo(32 * u, 32 * u); lineTo(56 * u, 56 * u)
                moveTo(56 * u, 32 * u); lineTo(32 * u, 56 * u)
            }
        }
        drawPath(path, Color.White, style = Stroke(6.5f * u, cap = StrokeCap.Round, join = StrokeJoin.Round))
    }
}
