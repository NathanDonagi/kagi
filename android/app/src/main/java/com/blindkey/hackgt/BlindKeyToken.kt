package com.blindkey.hackgt

import java.nio.charset.StandardCharsets

/**
 * Small opaque handle stored on commodity NFC tags.
 *
 * The tag intentionally does not contain the signed BlindKey credential or any
 * plaintext identity attributes. The backend resolves this handle to the
 * Authority-signed credential before running Nathan's existing verifier.
 */
data class BlindKeyToken private constructor(val value: String) {
    val byteCount: Int get() = value.toByteArray(StandardCharsets.US_ASCII).size

    companion object {
        private val FORMAT = Regex("^bk1:[A-Za-z0-9_-]{8,64}$")
        const val MAXIMUM_PAYLOAD_BYTES = 96

        fun parse(bytes: ByteArray): BlindKeyToken {
            require(bytes.size <= MAXIMUM_PAYLOAD_BYTES) { "BlindKey tag token is unexpectedly large." }
            val text = bytes.toString(StandardCharsets.US_ASCII).trim()
            require(FORMAT.matches(text)) { "NFC record is not a BlindKey token." }
            return BlindKeyToken(text)
        }

        fun parse(text: String): BlindKeyToken = parse(text.toByteArray(StandardCharsets.US_ASCII))
    }
}
