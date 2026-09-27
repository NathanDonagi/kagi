package com.example.kagi

import android.nfc.NfcAdapter
import android.nfc.Tag
import android.nfc.tech.NfcA
import android.nfc.tech.NfcB
import android.nfc.tech.NfcF
import android.nfc.tech.NfcV

/**
 * Tells the pass key from the fail key by the tag's UID. The UID arrives with
 * the tag's discovery (anticollision), so recognising a tap needs no further
 * I/O and a brief or wobbly tap is enough. (Reading the NDEF content instead
 * failed whenever the tag moved mid-read.)
 */
object TagReader {
    const val ALL_TECH = NfcAdapter.FLAG_READER_NFC_A or NfcAdapter.FLAG_READER_NFC_B or
        NfcAdapter.FLAG_READER_NFC_F or NfcAdapter.FLAG_READER_NFC_V

    fun idOf(tag: Tag): String = "uid:" + (tag.id ?: ByteArray(0)).joinToString("") { "%02x".format(it) }

    /** The reader-mode flags that find this tag. */
    fun techOf(tag: Tag): Int {
        val t = tag.techList.toSet()
        var flags = 0
        if (NfcA::class.java.name in t) flags = flags or NfcAdapter.FLAG_READER_NFC_A
        if (NfcB::class.java.name in t) flags = flags or NfcAdapter.FLAG_READER_NFC_B
        if (NfcF::class.java.name in t) flags = flags or NfcAdapter.FLAG_READER_NFC_F
        if (NfcV::class.java.name in t) flags = flags or NfcAdapter.FLAG_READER_NFC_V
        return flags
    }
}
