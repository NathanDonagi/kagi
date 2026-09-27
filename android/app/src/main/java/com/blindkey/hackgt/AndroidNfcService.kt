package com.blindkey.hackgt

import android.app.Activity
import android.nfc.NdefRecord
import android.nfc.NfcAdapter
import android.nfc.Tag
import android.nfc.tech.IsoDep
import android.nfc.tech.MifareClassic
import android.nfc.tech.MifareUltralight
import android.nfc.tech.Ndef
import android.nfc.tech.NfcF
import android.nfc.tech.NfcV
import android.os.Handler
import android.os.Looper
import java.nio.charset.Charset
import java.nio.charset.StandardCharsets
import java.util.concurrent.atomic.AtomicBoolean

class AndroidNfcService(private val activity: Activity) : NfcAdapter.ReaderCallback {
    companion object {
        private const val SCAN_TIMEOUT_MS = 20_000L
        private const val MAX_NDEF_RECORDS_TO_INSPECT = 16
    }

    private val adapter: NfcAdapter? = NfcAdapter.getDefaultAdapter(activity)
    private val mainHandler = Handler(Looper.getMainLooper())

    @Volatile
    private var callback: ((NfcScanResult) -> Unit)? = null
    private val completed = AtomicBoolean(false)

    private val timeoutRunnable = Runnable {
        finish(NfcScanResult.Failed("NFC scan timed out. Move the BlindKey tag near the phone and try again."))
    }

    val isAvailable: Boolean
        get() = adapter != null && adapter.isEnabled

    val unavailableReason: String?
        get() = when {
            adapter == null -> "This Android device does not have NFC hardware."
            !adapter.isEnabled -> "NFC is turned off. Enable NFC in Android Settings and try again."
            else -> null
        }

    fun startScan(callback: (NfcScanResult) -> Unit) {
        unavailableReason?.let {
            callback(NfcScanResult.Failed(it))
            return
        }

        this.callback = callback
        completed.set(false)
        mainHandler.removeCallbacks(timeoutRunnable)

        activity.runOnUiThread {
            if (completed.get()) return@runOnUiThread
            try {
                adapter?.enableReaderMode(
                    activity,
                    this,
                    NfcAdapter.FLAG_READER_NFC_A or
                        NfcAdapter.FLAG_READER_NFC_B or
                        NfcAdapter.FLAG_READER_NFC_F or
                        NfcAdapter.FLAG_READER_NFC_V,
                    null
                )
                mainHandler.postDelayed(timeoutRunnable, SCAN_TIMEOUT_MS)
            } catch (e: Exception) {
                finish(NfcScanResult.Failed(e.message ?: "Unable to start NFC reader mode."))
            }
        }
    }

    fun cancel() {
        completed.set(true)
        mainHandler.removeCallbacks(timeoutRunnable)
        callback = null

        activity.runOnUiThread {
            runCatching {
                adapter?.disableReaderMode(activity)
            }
        }
    }

    override fun onTagDiscovered(tag: Tag) {
        if (completed.get()) return
        val diagnostic = diagnosticFor(tag)

        try {
            val ndef = Ndef.get(tag)
            if (ndef == null) {
                finish(NfcScanResult.TagWithoutToken(diagnostic))
                return
            }

            val message = try {
                ndef.connect()
                ndef.cachedNdefMessage ?: ndef.ndefMessage
            } finally {
                runCatching { ndef.close() }
            }

            if (message == null || message.records.isEmpty()) {
                finish(NfcScanResult.TagWithoutToken(diagnostic))
                return
            }

            val token = extractToken(message.records)
            if (token == null) {
                finish(NfcScanResult.TagWithoutToken(diagnostic))
            } else {
                finish(NfcScanResult.Token(token, diagnostic))
            }
        } catch (e: Exception) {
            finish(NfcScanResult.Failed(e.message ?: "Unable to read NFC tag."))
        }
    }

    private fun finish(result: NfcScanResult) {
        if (!completed.compareAndSet(false, true)) return

        mainHandler.removeCallbacks(timeoutRunnable)

        val cb = callback
        callback = null

        activity.runOnUiThread {
            cb?.invoke(result)
        }
    }

    private fun diagnosticFor(tag: Tag): NfcTagDiagnostic {
        val technologies = tag.techList.map { it.substringAfterLast('.') }.sorted()
        val ndef = Ndef.get(tag)
        val family = when {
            technologies.contains(IsoDep::class.java.simpleName) -> NfcTagFamily.ISO_DEP
            technologies.contains(MifareClassic::class.java.simpleName) ||
                technologies.contains(MifareUltralight::class.java.simpleName) -> NfcTagFamily.MIFARE
            technologies.contains(NfcV::class.java.simpleName) -> NfcTagFamily.NFC_V
            technologies.contains(NfcF::class.java.simpleName) -> NfcTagFamily.NFC_F
            else -> NfcTagFamily.OTHER
        }

        return NfcTagDiagnostic(
            family = family,
            technologies = technologies,
            ndefSupported = ndef != null,
            ndefWritable = ndef?.isWritable,
            ndefCapacityBytes = ndef?.maxSize,
            identifierByteCount = tag.id?.size ?: 0
        )
    }

    private fun extractToken(records: Array<NdefRecord>): BlindKeyToken? {
        // Each record is considered independently. BlindKey tokens are tiny opaque
        // handles (bk1:...) so unrelated URLs/text records are ignored rather than
        // being combined into an ambiguous payload.
        for (record in records.take(MAX_NDEF_RECORDS_TO_INSPECT)) {
            val payload = decodePayload(record) ?: continue
            if (payload.isEmpty() || payload.size > BlindKeyToken.MAXIMUM_PAYLOAD_BYTES) continue
            try {
                return BlindKeyToken.parse(payload)
            } catch (_: Exception) {
                // Not a BlindKey token; inspect the next record.
            }
        }
        return null
    }

    private fun decodePayload(record: NdefRecord): ByteArray? {
        if (record.tnf == NdefRecord.TNF_WELL_KNOWN && record.type.contentEquals(NdefRecord.RTD_TEXT)) {
            return decodeTextRecord(record.payload)?.toByteArray(StandardCharsets.US_ASCII)
        }
        if (record.tnf == NdefRecord.TNF_MIME_MEDIA || record.tnf == NdefRecord.TNF_EXTERNAL_TYPE) {
            return record.payload.takeIf { it.isNotEmpty() }
        }
        return null
    }

    private fun decodeTextRecord(payload: ByteArray): String? {
        if (payload.isEmpty()) return null
        val status = payload[0].toInt() and 0xFF
        val languageLength = status and 0x3F
        val utf16 = (status and 0x80) != 0
        val textStart = 1 + languageLength
        if (textStart > payload.size) return null
        val charset: Charset = if (utf16) Charsets.UTF_16 else Charsets.UTF_8
        return payload.copyOfRange(textStart, payload.size).toString(charset).trim()
    }
}
