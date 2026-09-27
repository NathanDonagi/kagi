package com.example.kagi.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.kagi.KagiViewModel
import com.example.kagi.Tag
import com.example.kagi.bridge.BridgeState
import com.example.kagi.ui.theme.LocalKagi

enum class NfcStatus { ON, OFF, MISSING }

@Composable
private fun Section(title: String) {
    Spacer(Modifier.height(32.dp))
    Text(title.uppercase(), color = LocalKagi.current.muted, fontSize = 13.sp, letterSpacing = 2.sp)
    Spacer(Modifier.height(12.dp))
}

@Composable
private fun Note(text: String) {
    Text(text, Modifier.padding(vertical = 4.dp), color = LocalKagi.current.muted, fontSize = 14.sp, lineHeight = 20.sp)
}

@Composable
fun SettingsScreen(vm: KagiViewModel, nfc: NfcStatus, bridge: BridgeState, requestBluetooth: () -> Unit) {
    val k = LocalKagi.current
    val s by vm.settings.collectAsState()

    Title("Settings")

    // ---- PC ----
    Section("PC")
    Note(
        when (bridge) {
            is BridgeState.Connected -> "Connected to ${bridge.name}."
            is BridgeState.Connecting -> "Connecting to ${bridge.name}..."
            is BridgeState.Reconnecting -> "Reconnecting to ${bridge.name}: ${bridge.why}"
            BridgeState.NotSetUp -> "Choose the PC running bluetooth_bridge.py."
            BridgeState.NoPermission -> "kagi needs permission to use Bluetooth."
        }
    )
    Spacer(Modifier.height(8.dp))
    val devices = remember(bridge) { vm.bondedDevices() }
    when {
        devices == null -> PrimaryButton("Allow Bluetooth", onClick = requestBluetooth)
        devices.isEmpty() -> Note("No paired devices. Pair the PC in Android's Bluetooth settings first.")
        else -> Column(
            Modifier.fillMaxWidth()
                .background(k.field, RoundedCornerShape(16.dp))
                .border(1.dp, k.line, RoundedCornerShape(16.dp))
                .padding(horizontal = 24.dp, vertical = 4.dp)
        ) {
            devices.forEachIndexed { i, (name, mac) ->
                if (i > 0) Box(Modifier.fillMaxWidth().height(1.dp).background(k.line))
                Row(
                    Modifier.fillMaxWidth()
                        .clickable { vm.updateSettings(s.copy(pcAddress = mac, pcName = name)) }
                        .padding(vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(name, color = k.ink, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                        Text(mac, color = k.muted, fontSize = 13.sp)
                    }
                    if (mac == s.pcAddress) Text("✓", color = k.green, fontSize = 20.sp)
                }
            }
        }
    }
    Spacer(Modifier.height(12.dp))
    var channel by remember { mutableStateOf(TextFieldValue(s.rfcommChannel?.toString() ?: "")) }
    Field(
        channel,
        {
            val digits = it.text.filter(Char::isDigit).take(2)
            channel = it.copy(text = digits)
            vm.updateSettings(s.copy(rfcommChannel = digits.toIntOrNull()?.takeIf { n -> n in 1..30 }))
        },
        "RFCOMM channel (only if connecting fails)",
        keyboard = KeyboardOptions(keyboardType = KeyboardType.Number),
    )
    Spacer(Modifier.height(8.dp))
    SwitchRow("Debug: TCP 127.0.0.1:8766 (adb reverse)", s.useTcp) { vm.updateSettings(s.copy(useTcp = it)) }

    // ---- NFC tags ----
    Section("NFC tags")
    when (nfc) {
        NfcStatus.MISSING -> Note("This phone has no NFC. Turn on simulated taps below to rehearse.")
        NfcStatus.OFF -> Note("NFC is off. Turn it on in Android's settings.")
        NfcStatus.ON -> {}
    }
    val enrolling by vm.enrolling.collectAsState()
    InfoCard(
        listOf(
            "Pass key" to (s.passTag?.let(::shortUid) ?: "Not set"),
            "Fail key" to (s.failTag?.let(::shortUid) ?: "Not set"),
        )
    )
    Spacer(Modifier.height(8.dp))
    Note("Pass key: Nathan Donagi's key, the same one as the Arduino. Fail key: someone else's, " +
        "under 18 and not registered, so every check fails.")
    Spacer(Modifier.height(8.dp))
    if (enrolling != null) {
        Muted("Hold the ${if (enrolling == Tag.PASS) "pass" else "fail"} tag against the back of the phone...")
        CenteredTextButton("Cancel") { vm.enroll(null) }
    } else {
        Row(Modifier.fillMaxWidth()) {
            Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
                TextButton("Register pass tag") { vm.enroll(Tag.PASS) }
            }
            Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
                TextButton("Register fail tag") { vm.enroll(Tag.FAIL) }
            }
        }
    }

    // ---- Debug ----
    Section("Debug")
    SwitchRow("Show simulated tap buttons", s.simulateTaps) { vm.updateSettings(s.copy(simulateTaps = it)) }
    SwitchRow("Recording mode: verify with the pass key after 3 s", s.autoVerify) {
        vm.updateSettings(s.copy(autoVerify = it))
    }
    Note("Tapping a real tag within the 3 seconds still uses that tag.")

    Spacer(Modifier.height(32.dp))
    PrimaryButton("Done") { vm.showCodeScreen() }
}

private fun shortUid(id: String) = id.removePrefix("uid:").chunked(2).joinToString(":").uppercase()
