package com.example.kagi.ui

import android.os.SystemClock
import androidx.activity.compose.BackHandler
import androidx.compose.animation.Animatable
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.kagi.Challenge
import com.example.kagi.KagiViewModel
import com.example.kagi.Phase
import com.example.kagi.Screen
import com.example.kagi.Tag
import com.example.kagi.bridge.BridgeState
import com.example.kagi.ui.theme.LocalKagi
import kotlinx.coroutines.delay

@Composable
fun KagiApp(vm: KagiViewModel, nfc: NfcStatus, requestBluetooth: () -> Unit) {
    val k = LocalKagi.current
    val screen by vm.screen.collectAsState()
    val bridge by vm.bridge.state.collectAsState()
    val bg = remember { Animatable(k.bg) }

    // The result tint: one gentle pulse of green that settles, or a flat red.
    val done = (screen as? Screen.Auth)?.phase as? Phase.Done
    LaunchedEffect(done, k) {
        when {
            done == null -> bg.snapTo(k.bg)
            done.ok -> {
                bg.snapTo(k.greenFlash)
                bg.animateTo(k.greenBg, tween(900, easing = CubicBezierEasing(0.33f, 1f, 0.68f, 1f)))
            }
            else -> bg.snapTo(k.redBg)
        }
    }

    if (screen !is Screen.Code) BackHandler { vm.showCodeScreen() }

    Box(Modifier.fillMaxSize().background(bg.value)) {
        Column(Modifier.fillMaxSize().safeDrawingPadding().imePadding()) {
            Box(
                Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(24.dp),
                contentAlignment = Alignment.Center,
            ) {
                // A centred column, 360 wide like the site.
                Column(Modifier.widthIn(max = 360.dp).fillMaxWidth()) {
                    Brand()
                    when (val s = screen) {
                        is Screen.Code -> CodeScreen(vm, s)
                        is Screen.Auth -> AuthScreen(vm, s)
                        Screen.Settings -> SettingsScreen(vm, nfc, bridge, requestBluetooth)
                    }
                }
            }
            if (screen !is Screen.Settings) StatusLine(bridge) { vm.openSettings() }
        }
    }
}

@Composable
private fun StatusLine(state: BridgeState, openSettings: () -> Unit) {
    val k = LocalKagi.current
    val (colour, text) = when (state) {
        is BridgeState.Connected -> k.green to "Connected to ${state.name}"
        is BridgeState.Connecting -> k.line to "Connecting to ${state.name}..."
        is BridgeState.Reconnecting -> k.line to "Reconnecting to PC..."
        BridgeState.NotSetUp -> k.red to "Choose your PC in Settings"
        BridgeState.NoPermission -> k.red to "Bluetooth permission needed"
    }
    Row(
        Modifier.fillMaxWidth().padding(start = 24.dp, end = 16.dp, bottom = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            buildAnnotatedString {
                withStyle(SpanStyle(color = colour)) { append("●") }
                append("  $text")
            },
            Modifier.weight(1f), color = k.muted, fontSize = 13.sp,
        )
        Text(
            "Settings", Modifier.clickable(onClick = openSettings).padding(8.dp), color = k.muted, fontSize = 13.sp,
        )
    }
}

// ---------- screen 1: enter code ----------

private fun formatCode(v: TextFieldValue): TextFieldValue {
    val digits = v.text.filter(Char::isDigit).take(12)
    val pretty = digits.chunked(4).joinToString(" ")
    return TextFieldValue(pretty, TextRange(pretty.length))
}

@Composable
private fun CodeScreen(vm: KagiViewModel, s: Screen.Code) {
    var code by remember { mutableStateOf(TextFieldValue("")) }
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { focus.requestFocus() }
    val submit = { if (!s.busy) vm.submitCode(code.text) }

    Title("Enter code")
    Spacer(Modifier.height(24.dp))
    Field(
        code, { code = formatCode(it) }, "0000 0000", Modifier.focusRequester(focus), style = CodeStyle,
        keyboard = KeyboardOptions(keyboardType = KeyboardType.NumberPassword, imeAction = ImeAction.Go),
        actions = KeyboardActions(onGo = { submit() }),
    )
    Spacer(Modifier.height(8.dp))
    ErrorText(s.error)
    Spacer(Modifier.height(8.dp))
    PrimaryButton(if (s.busy) "Looking up..." else "Continue", enabled = !s.busy) { submit() }
}

@Composable
private fun AgeHeader(ch: Challenge) {
    Muted("${ch.siteName} wants to check your age")
    Spacer(Modifier.height(16.dp))
    InfoCard(listOf("Question" to "${ch.over} or over?", "They learn" to "Yes or no"))
}

@Composable
fun CenteredTextButton(text: String, onClick: () -> Unit) {
    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) { TextButton(text, onClick = onClick) }
}

// ---------- screen 2: show the request, then authenticate ----------

@Composable
private fun AuthScreen(vm: KagiViewModel, s: Screen.Auth) {
    val k = LocalKagi.current
    val ch = s.ch
    val settings by vm.settings.collectAsState()
    when (ch.kind) {
        Challenge.Kind.NAME_CHECK -> {
            Muted("Someone is asking you to confirm")
            Spacer(Modifier.height(16.dp))
            InfoCard(listOf("First name" to ch.firstName, "Last name" to ch.lastName))
        }
        Challenge.Kind.UNIQUE_SIGNUP -> {
            Muted("${ch.siteName} wants to check you're a unique person")
            Spacer(Modifier.height(16.dp))
            InfoCard(listOf("Site" to ch.siteName, "They learn" to "New or existing"))
        }
        Challenge.Kind.AGE_CHECK -> AgeHeader(ch)
    }
    val phase = s.phase
    Spacer(Modifier.height(12.dp))
    if (phase !is Phase.Done) Countdown(ch.expiresAt) else Spacer(Modifier.height(18.dp))
    Spacer(Modifier.height(28.dp))

    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        StatusIcon(
            when {
                phase !is Phase.Done -> IconMode.SPIN
                phase.ok -> IconMode.OK
                else -> IconMode.FAIL
            }
        )
    }
    Spacer(Modifier.height(20.dp))
    val (headline, sub) = when (phase) {
        is Phase.Tap -> "Please authenticate now" to (phase.note ?: "Tap your key on the back of the phone.")
        Phase.Checking -> "Checking your key..." to "Keep it near the phone."
        Phase.Sending -> "Almost done..." to "Sending your key's answer."
        is Phase.Done -> phase.headline to phase.message
    }
    Title(headline, if (phase is Phase.Done) (if (phase.ok) k.green else k.red) else k.ink)
    Spacer(Modifier.height(6.dp))
    Muted(sub, modifier = Modifier.heightIn(min = 48.dp))
    Spacer(Modifier.height(12.dp))

    if (phase is Phase.Tap && settings.simulateTaps) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
            TextButton("Simulate pass key") { vm.simulateTap(Tag.PASS) }
            TextButton("Simulate fail key") { vm.simulateTap(Tag.FAIL) }
        }
        Spacer(Modifier.height(8.dp))
    }
    if (phase is Phase.Done && phase.canRetry) {
        PrimaryButton("Try again") { vm.retry() }
        Spacer(Modifier.height(4.dp))
    }
    CenteredTextButton(if (phase is Phase.Done) "Done" else "Cancel") { vm.showCodeScreen() }
}

/** "Code expires in 4:59" (communication.md §3.1: codes last 5 minutes). */
@Composable
private fun Countdown(expiresAt: Long) {
    var now by remember { mutableLongStateOf(SystemClock.elapsedRealtime()) }
    LaunchedEffect(expiresAt) {
        while (true) {
            now = SystemClock.elapsedRealtime()
            delay(250)
        }
    }
    val left = ((expiresAt - now) / 1000).coerceAtLeast(0)
    Muted("Code expires in ${left / 60}:${"%02d".format(left % 60)}", 13.sp, Modifier.heightIn(min = 18.dp))
}
