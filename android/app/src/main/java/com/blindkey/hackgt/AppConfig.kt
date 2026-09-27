package com.blindkey.hackgt

import android.content.Context
import android.os.Build

class AppConfig(context: Context) {
    private val prefs = context.getSharedPreferences("blindkey", Context.MODE_PRIVATE)

    var backendBaseUrl: String
        get() = prefs.getString(KEY_BACKEND_URL, defaultBackendUrl()) ?: defaultBackendUrl()
        set(value) { prefs.edit().putString(KEY_BACKEND_URL, value.trim()).apply() }

    var showDebugTools: Boolean
        get() = prefs.getBoolean(KEY_DEBUG_TOOLS, false)
        set(value) { prefs.edit().putBoolean(KEY_DEBUG_TOOLS, value).apply() }

    var trustedBackendUrl: String?
        get() = prefs.getString(KEY_TRUSTED_BACKEND_URL, null)
        private set(value) { prefs.edit().putString(KEY_TRUSTED_BACKEND_URL, value).apply() }

    var trustedAuthorityFingerprint: String?
        get() = prefs.getString(KEY_TRUSTED_AUTHORITY_FINGERPRINT, null)
        private set(value) { prefs.edit().putString(KEY_TRUSTED_AUTHORITY_FINGERPRINT, value).apply() }

    fun trustBackend(normalizedUrl: String, authorityFingerprint: String) {
        prefs.edit()
            .putString(KEY_TRUSTED_BACKEND_URL, normalizedUrl)
            .putString(KEY_TRUSTED_AUTHORITY_FINGERPRINT, authorityFingerprint)
            .apply()
    }

    fun clearBackendTrust() {
        prefs.edit()
            .remove(KEY_TRUSTED_BACKEND_URL)
            .remove(KEY_TRUSTED_AUTHORITY_FINGERPRINT)
            .apply()
    }

    fun trustedFingerprintFor(normalizedUrl: String): String? {
        return trustedAuthorityFingerprint?.takeIf { trustedBackendUrl == normalizedUrl }
    }

    companion object {
        private const val KEY_BACKEND_URL = "backendBaseUrl"
        private const val KEY_DEBUG_TOOLS = "showDebugTools"
        private const val KEY_TRUSTED_BACKEND_URL = "trustedBackendUrl"
        private const val KEY_TRUSTED_AUTHORITY_FINGERPRINT = "trustedAuthorityFingerprint"

        fun isEmulator(): Boolean {
            val fingerprint = Build.FINGERPRINT.lowercase()
            val model = Build.MODEL.lowercase()
            return fingerprint.contains("generic") ||
                fingerprint.contains("emulator") ||
                model.contains("emulator") ||
                model.contains("android sdk built for")
        }

        fun defaultBackendUrl(): String = if (isEmulator()) {
            // Android Emulator's special alias for the host Mac/PC.
            "http://10.0.2.2:8000"
        } else {
            ""
        }
    }
}
