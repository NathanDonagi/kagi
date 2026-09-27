package com.example.kagi

import android.content.Context

/** Everything the user sets up once. The keys themselves are in DemoKeys. */
data class Settings(
    val pcAddress: String? = null,      // MAC of the paired PC running bluetooth_bridge.py
    val pcName: String? = null,
    val rfcommChannel: Int? = null,     // communication.md §1 fallback
    val useTcp: Boolean = false,        // debug: 127.0.0.1:8766 via `adb reverse`
    val passTag: String? = null,        // tag ids, "uid:<hex>" (see TagReader)
    val failTag: String? = null,
    val passTech: Int = 0,              // NfcAdapter.FLAG_READER_* the tag answers to (0: unknown)
    val failTech: Int = 0,
    val simulateTaps: Boolean = false,  // on-screen stand-ins for the tags (emulator, no NFC)
    val autoVerify: Boolean = false,    // for recording: the pass key "taps" itself after 3 s
) {
    /** Only poll for the kinds of tag we registered: each poll cycle is then shorter,
     *  so a tag held against the phone is picked up sooner and more reliably. */
    val readerTech: Int
        get() = if (passTech != 0 && failTech != 0) passTech or failTech else TagReader.ALL_TECH

    class Store(context: Context) {
        private val prefs = context.getSharedPreferences("kagi_settings", Context.MODE_PRIVATE)

        fun load() = Settings(
            pcAddress = prefs.getString("pc_address", null),
            pcName = prefs.getString("pc_name", null),
            rfcommChannel = prefs.getInt("rfcomm_channel", 0).takeIf { it > 0 },
            useTcp = prefs.getBoolean("use_tcp", false),
            // Tags registered by NDEF content (earlier builds) must be registered again.
            passTag = prefs.getString("pass_tag", null)?.takeIf { it.startsWith("uid:") },
            failTag = prefs.getString("fail_tag", null)?.takeIf { it.startsWith("uid:") },
            passTech = prefs.getInt("pass_tech", 0),
            failTech = prefs.getInt("fail_tech", 0),
            simulateTaps = prefs.getBoolean("simulate_taps", false),
            autoVerify = prefs.getBoolean("auto_verify", false),
        )

        fun save(s: Settings) = prefs.edit()
            .putString("pc_address", s.pcAddress)
            .putString("pc_name", s.pcName)
            .putInt("rfcomm_channel", s.rfcommChannel ?: 0)
            .putBoolean("use_tcp", s.useTcp)
            .putString("pass_tag", s.passTag)
            .putString("fail_tag", s.failTag)
            .putInt("pass_tech", s.passTech)
            .putInt("fail_tech", s.failTech)
            .putBoolean("simulate_taps", s.simulateTaps)
            .putBoolean("auto_verify", s.autoVerify)
            .apply()
    }
}
