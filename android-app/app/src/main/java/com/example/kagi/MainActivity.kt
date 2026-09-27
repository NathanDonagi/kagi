package com.example.kagi

import android.Manifest
import android.nfc.NfcAdapter
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.example.kagi.bridge.hasBluetoothPermission
import com.example.kagi.ui.KagiApp
import com.example.kagi.ui.NfcStatus
import com.example.kagi.ui.theme.KagiTheme

class MainActivity : ComponentActivity() {
    private val vm: KagiViewModel by viewModels()
    private var nfc: NfcAdapter? = null
    private var nfcStatus by mutableStateOf(NfcStatus.MISSING)

    private val bluetoothPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { vm.restartBridge() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)     // it's a demo
        enableEdgeToEdge()
        nfc = NfcAdapter.getDefaultAdapter(this)
        if (!hasBluetoothPermission(this)) requestBluetooth()
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.RESUMED) {
                combine(vm.settings, vm.enrolling, ::wantedTech).collect { if (it != readerTech) startReader(it) }
            }
        }
        setContent {
            KagiTheme {
                KagiApp(vm, nfcStatus, ::requestBluetooth)
            }
        }
    }

    private fun requestBluetooth() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            bluetoothPermission.launch(Manifest.permission.BLUETOOTH_CONNECT)
        }
    }

    // The key tags are read whenever the app is in front; the view model decides
    // whether anything is waiting for one.
    override fun onResume() {
        super.onResume()
        val adapter = nfc
        nfcStatus = when {
            adapter == null -> NfcStatus.MISSING
            !adapter.isEnabled -> NfcStatus.OFF
            else -> NfcStatus.ON
        }
        startReader(wantedTech(vm.settings.value, vm.enrolling.value))
    }

    private var readerTech = 0

    /** While registering a tag, look for every kind; otherwise just the registered ones. */
    private fun wantedTech(s: Settings, enrolling: Tag?) = if (enrolling != null) TagReader.ALL_TECH else s.readerTech

    /** Reader mode, polling only for the registered tags' technologies. The UID
     *  is all we need, so skip the platform's NDEF check (it slows every tap). */
    private fun startReader(tech: Int) {
        val adapter = nfc ?: return
        readerTech = tech
        adapter.enableReaderMode(
            this,
            { tag -> vm.onTag(TagReader.idOf(tag), TagReader.techOf(tag)) },
            tech or NfcAdapter.FLAG_READER_SKIP_NDEF_CHECK,
            null,
        )
    }

    override fun onPause() {
        super.onPause()
        nfc?.disableReaderMode(this)
    }
}
