package com.blindkey.hackgt

import android.app.Activity
import androidx.activity.compose.BackHandler
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle

private val SignalRed = Color(0xFFE5484D)
private val SignalYellow = Color(0xFFF5A524)
private val SignalGreen = Color(0xFF30A46C)

@Composable
fun BlindKeyApp(vm: VerificationViewModel, activity: Activity) {
    val state by vm.state.collectAsStateWithLifecycle()
    val lastDiagnostic by vm.lastDiagnostic.collectAsStateWithLifecycle()
    val backendUrl by vm.backendUrl.collectAsStateWithLifecycle()
    val showDebugTools by vm.showDebugTools.collectAsStateWithLifecycle()
    val backendTestMessage by vm.backendTestMessage.collectAsStateWithLifecycle()
    val isTestingBackend by vm.isTestingBackend.collectAsStateWithLifecycle()

    val nfcService = remember(activity) { AndroidNfcService(activity) }
    var showSettings by remember { mutableStateOf(false) }
    val haptics = LocalHapticFeedback.current
    val lifecycleOwner = LocalLifecycleOwner.current

    BackHandler(enabled = state !is VerificationState.Idle) {
        vm.reset()
    }

    DisposableEffect(lifecycleOwner, nfcService) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_PAUSE) {
                nfcService.cancel()
                vm.cancelActiveScanForLifecycle()
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            nfcService.cancel()
        }
    }

    LaunchedEffect(state) {
        when (state) {
            is VerificationState.Verified -> haptics.performHapticFeedback(HapticFeedbackType.LongPress)
            is VerificationState.Denied -> haptics.performHapticFeedback(HapticFeedbackType.LongPress)
            is VerificationState.Error -> haptics.performHapticFeedback(HapticFeedbackType.LongPress)
            else -> Unit
        }
    }

    Surface(modifier = Modifier.fillMaxSize()) {
        when (state) {
            VerificationState.Idle -> QueryPickerScreen(
                showDebugTools = showDebugTools,
                onSelect = vm::selectQuery,
                onSettings = { showSettings = true }
            )

            else -> VerificationScreen(
                state = state,
                diagnostic = lastDiagnostic,
                showDebugTools = showDebugTools,
                onStartScan = { vm.startScan(nfcService) },
                onRetry = vm::retry,
                onReset = vm::reset,
                onForceVerified = vm::debugForceVerified,
                onForceDenied = vm::debugForceDenied,
                onSettings = { showSettings = true }
            )
        }
    }

    if (showSettings) {
        BackendSettingsDialog(
            backendUrl = backendUrl,
            showDebugTools = showDebugTools,
            testMessage = backendTestMessage,
            isTesting = isTestingBackend,
            onBackendUrlChange = vm::updateBackendUrl,
            onDebugToolsChange = vm::updateDebugTools,
            onTest = vm::testBackend,
            onDismiss = { showSettings = false }
        )
    }
}

@Composable
private fun QueryPickerScreen(
    showDebugTools: Boolean,
    onSelect: (VerificationQuery) -> Unit,
    onSettings: () -> Unit
) {
    val queries = if (showDebugTools) {
        VerificationQuery.primaryDemoCases + VerificationQuery.advancedDemoCases
    } else {
        VerificationQuery.primaryDemoCases
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 20.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Column {
                Text(
                    "BLINDKEY",
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.SemiBold,
                    letterSpacing = 5.sp,
                    style = MaterialTheme.typography.labelLarge
                )
                Text(
                    "SELECTIVE IDENTITY VERIFICATION",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 11.sp,
                    letterSpacing = 1.sp
                )
            }
            TextButton(onClick = onSettings) { Text("⚙ Settings") }
        }

        Spacer(Modifier.height(56.dp))

        Text(
            "What should this credential prove?",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
            textAlign = TextAlign.Center
        )
        Spacer(Modifier.height(10.dp))
        Text(
            "BlindKey answers the requested claim without exposing the full identity record.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center
        )

        Spacer(Modifier.height(32.dp))

        queries.forEach { query ->
            OutlinedButton(
                onClick = { onSelect(query) },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 6.dp),
                shape = RoundedCornerShape(16.dp)
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 8.dp),
                    horizontalAlignment = Alignment.Start
                ) {
                    Text(query.label, fontWeight = FontWeight.Bold)
                    Text(
                        query.humanQuestion,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }

        Spacer(Modifier.height(36.dp))
        Text(
            "Opaque NFC token → exact query → pass / deny",
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Composable
private fun VerificationScreen(
    state: VerificationState,
    diagnostic: NfcTagDiagnostic?,
    showDebugTools: Boolean,
    onStartScan: () -> Unit,
    onRetry: () -> Unit,
    onReset: () -> Unit,
    onForceVerified: () -> Unit,
    onForceDenied: () -> Unit,
    onSettings: () -> Unit
) {
    val query = state.query ?: return

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 28.dp, vertical = 20.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Text(
                "BLINDKEY",
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.SemiBold,
                letterSpacing = 5.sp,
                style = MaterialTheme.typography.labelLarge
            )
            TextButton(onClick = onSettings) { Text("⚙ Settings") }
        }

        Spacer(Modifier.height(24.dp))

        Text(
            "VERIFICATION REQUEST",
            fontFamily = FontFamily.Monospace,
            letterSpacing = 2.sp,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(Modifier.height(12.dp))
        Text(
            query.label.uppercase(),
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(Modifier.height(6.dp))
        Text(
            query.humanQuestion,
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.SemiBold,
            textAlign = TextAlign.Center
        )

        Spacer(Modifier.height(28.dp))
        TrafficLightView(state.trafficLight)
        Spacer(Modifier.height(26.dp))

        val statusColor = when {
            state is VerificationState.Error -> SignalYellow
            state.trafficLight == TrafficLight.GREEN -> SignalGreen
            state.trafficLight == TrafficLight.RED -> SignalRed
            else -> MaterialTheme.colorScheme.onSurface
        }

        Text(
            state.statusText,
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
            color = statusColor,
            textAlign = TextAlign.Center
        )

        when (state) {
            is VerificationState.Verified -> SupportingText("Requested claim proven.")
            is VerificationState.Denied -> SupportingText("The authentic credential did not satisfy this query.")
            is VerificationState.Verifying -> SupportingText("Resolving the NFC token and checking the signed credential with the BlindKey verifier.")
            is VerificationState.Error -> SupportingText(state.message)
            else -> Unit
        }

        Spacer(Modifier.height(26.dp))

        when (state) {
            is VerificationState.QueryReady -> {
                PrimaryButton("Scan Credential", onStartScan)
                SecondaryButton("Change Query", onReset)
            }
            is VerificationState.Scanning -> {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(modifier = Modifier.size(22.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(10.dp))
                    Text("Hold the BlindKey tag near the NFC area of your phone…")
                }
                Spacer(Modifier.height(14.dp))
                SecondaryButton("Cancel", onRetry)
            }
            is VerificationState.TagDetected, is VerificationState.Verifying -> {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(modifier = Modifier.size(22.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(10.dp))
                    Text("Verifying credential…")
                }
            }
            is VerificationState.Verified, is VerificationState.Denied -> {
                PrimaryButton("Scan Another Credential", onRetry)
                SecondaryButton("Change Query", onReset)
            }
            is VerificationState.Error -> {
                PrimaryButton("Try Again", onRetry)
                SecondaryButton("Change Query", onReset)
            }
            else -> Unit
        }

        if (showDebugTools) {
            Spacer(Modifier.height(28.dp))
            HorizontalDivider()
            Spacer(Modifier.height(18.dp))
            Text(
                "DEBUG",
                fontFamily = FontFamily.Monospace,
                letterSpacing = 4.sp,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            diagnostic?.let {
                Spacer(Modifier.height(10.dp))
                Text(
                    it.debugSummary,
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(12.dp))
                        .padding(12.dp),
                    fontFamily = FontFamily.Monospace,
                    style = MaterialTheme.typography.bodySmall
                )
            }
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(onClick = onForceVerified, modifier = Modifier.weight(1f)) {
                    Text("Force GREEN")
                }
                OutlinedButton(onClick = onForceDenied, modifier = Modifier.weight(1f)) {
                    Text("Force RED")
                }
            }
        }

        Spacer(Modifier.height(32.dp))
    }
}

@Composable
private fun TrafficLightView(active: TrafficLight) {
    Column(
        modifier = Modifier
            .background(Color(0xFF171717), RoundedCornerShape(28.dp))
            .padding(horizontal = 24.dp, vertical = 20.dp)
            .semantics {
                contentDescription = when (active) {
                    TrafficLight.RED -> "Denied, red light active"
                    TrafficLight.YELLOW -> "Pending, yellow light active"
                    TrafficLight.GREEN -> "Verified, green light active"
                }
            },
        verticalArrangement = Arrangement.spacedBy(14.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        SignalLamp(SignalRed, active == TrafficLight.RED, "×")
        SignalLamp(SignalYellow, active == TrafficLight.YELLOW, "…")
        SignalLamp(SignalGreen, active == TrafficLight.GREEN, "✓")
    }
}

@Composable
private fun SignalLamp(color: Color, active: Boolean, symbol: String) {
    val fill by animateColorAsState(
        targetValue = if (active) color else color.copy(alpha = 0.16f),
        label = "signal"
    )
    Box(
        modifier = Modifier
            .size(76.dp)
            .background(fill, CircleShape)
            .border(2.dp, color.copy(alpha = if (active) 0.9f else 0.2f), CircleShape),
        contentAlignment = Alignment.Center
    ) {
        Text(
            if (active) symbol else "",
            color = Color.White,
            fontSize = 30.sp,
            fontWeight = FontWeight.Bold
        )
    }
}

@Composable
private fun SupportingText(text: String) {
    Spacer(Modifier.height(8.dp))
    Text(
        text,
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        textAlign = TextAlign.Center
    )
}

@Composable
private fun PrimaryButton(title: String, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp)
    ) {
        Text(title, modifier = Modifier.padding(vertical = 6.dp), fontWeight = FontWeight.Bold)
    }
    Spacer(Modifier.height(10.dp))
}

@Composable
private fun SecondaryButton(title: String, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick,
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp)
    ) {
        Text(title, modifier = Modifier.padding(vertical = 6.dp), fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun BackendSettingsDialog(
    backendUrl: String,
    showDebugTools: Boolean,
    testMessage: String?,
    isTesting: Boolean,
    onBackendUrlChange: (String) -> Unit,
    onDebugToolsChange: (Boolean) -> Unit,
    onTest: () -> Unit,
    onDismiss: () -> Unit
) {
    var draftUrl by remember(backendUrl) { mutableStateOf(backendUrl) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("BlindKey Backend") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Text(
                    if (AppConfig.isEmulator()) {
                        "The Android emulator uses 10.0.2.2 to reach your Mac."
                    } else {
                        "Most reliable demo: connect by USB, run scripts/start_usb_demo.sh on the Mac, then use http://127.0.0.1:8000. LAN IP also works when devices can reach each other."
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                OutlinedTextField(
                    value = draftUrl,
                    onValueChange = {
                        draftUrl = it
                        onBackendUrlChange(it)
                    },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    label = { Text("Backend URL") },
                    placeholder = { Text("http://192.168.x.x:8000") }
                )
                if (!AppConfig.isEmulator()) {
                    OutlinedButton(
                        onClick = {
                            val usbUrl = "http://127.0.0.1:8000"
                            draftUrl = usbUrl
                            onBackendUrlChange(usbUrl)
                        },
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("Use USB demo URL")
                    }
                }
                Button(
                    onClick = onTest,
                    enabled = !isTesting,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    if (isTesting) {
                        CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                        Spacer(Modifier.width(8.dp))
                    }
                    Text(if (isTesting) "Testing…" else "Test Connection")
                }
                testMessage?.let {
                    Text(
                        it,
                        style = MaterialTheme.typography.bodySmall,
                        color = if (it.startsWith("Connected")) SignalGreen else MaterialTheme.colorScheme.error
                    )
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("Show debug controls", fontWeight = FontWeight.SemiBold)
                        Text(
                            "NFC diagnostics and Force GREEN/RED. Keep off for judging.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    Switch(checked = showDebugTools, onCheckedChange = onDebugToolsChange)
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text("Done") }
        }
    )
}
