package com.blindkey.hackgt

enum class NfcTagFamily(val displayName: String) {
    ISO_DEP("ISO 14443 / ISO-DEP"),
    MIFARE("MIFARE"),
    NFC_V("ISO 15693 / NFC-V"),
    NFC_F("FeliCa / NFC-F"),
    OTHER("Other")
}

data class NfcTagDiagnostic(
    val family: NfcTagFamily,
    val technologies: List<String>,
    val ndefSupported: Boolean,
    val ndefWritable: Boolean?,
    val ndefCapacityBytes: Int?,
    val identifierByteCount: Int
) {
    val debugSummary: String
        get() = buildString {
            appendLine("Tag family: ${family.displayName}")
            appendLine("Technologies: ${technologies.joinToString()}")
            appendLine("NDEF: ${if (ndefSupported) "supported" else "not supported"}")
            ndefWritable?.let { appendLine("Writable: $it") }
            ndefCapacityBytes?.let { appendLine("NDEF capacity: $it bytes") }
            append("ID length: $identifierByteCount bytes")
        }
}

sealed interface NfcScanResult {
    data class Token(
        val token: BlindKeyToken,
        val diagnostic: NfcTagDiagnostic
    ) : NfcScanResult

    data class TagWithoutToken(val diagnostic: NfcTagDiagnostic) : NfcScanResult
    data class Failed(val message: String) : NfcScanResult
}
