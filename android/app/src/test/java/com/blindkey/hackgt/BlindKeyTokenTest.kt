package com.blindkey.hackgt

import org.junit.Assert.assertEquals
import org.junit.Test

class BlindKeyTokenTest {
    @Test
    fun demoTokenParsesAndStaysTiny() {
        val token = BlindKeyToken.parse("bk1:UtVTrXmW8_2nNB-H")
        assertEquals("bk1:UtVTrXmW8_2nNB-H", token.value)
        assertEquals(20, token.byteCount)
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsNonBlindKeyText() {
        BlindKeyToken.parse("https://tagstand.com/welcome")
    }

    @Test
    fun over21QueryMatchesBackendContract() {
        val json = VerificationQuery.over21.toJson()
        assertEquals("Nathan", json.getString("first_name"))
        assertEquals("Donagi", json.getString("last_name"))
        assertEquals(21, json.getInt("over"))
        assertEquals(3, json.length())
        assertEquals("OVER21", VerificationQuery.over21.expectedScope)
    }
}
