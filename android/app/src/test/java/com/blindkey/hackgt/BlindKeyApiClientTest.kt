package com.blindkey.hackgt

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BlindKeyApiClientTest {
    private val client = BlindKeyApiClient()

    @Test
    fun acceptsServerOriginAndNormalizesTrailingSlash() {
        assertEquals("http://192.168.1.20:8000", client.validateBaseUrl("http://192.168.1.20:8000/"))
        assertEquals("https://blindkey.example", client.validateBaseUrl("https://blindkey.example"))
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsEmbeddedCredentials() {
        client.validateBaseUrl("http://user:pass@192.168.1.20:8000")
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsBackendPath() {
        client.validateBaseUrl("http://192.168.1.20:8000/api")
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsUnsupportedScheme() {
        client.validateBaseUrl("ftp://192.168.1.20:8000")
    }

    @Test
    fun parsesExpectedVerifiedScope() {
        val result = client.parseVerificationResponse(
            """{"verified":true,"scope":"OVER21","error":null}""",
            VerificationQuery.over21
        )
        assertTrue(result.verified)
        assertEquals("OVER21", result.scope)
        assertEquals(null, result.error)
    }

    @Test
    fun parsesNormalDenialWithoutTurningItIntoAnError() {
        val result = client.parseVerificationResponse(
            """{"verified":false,"scope":null,"error":null}""",
            VerificationQuery.over21
        )
        assertFalse(result.verified)
        assertEquals(null, result.scope)
        assertEquals(null, result.error)
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsUnexpectedSuccessScope() {
        client.parseVerificationResponse(
            """{"verified":true,"scope":"L1","error":null}""",
            VerificationQuery.over21
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsScopeOnFailedVerification() {
        client.parseVerificationResponse(
            """{"verified":false,"scope":"OVER21","error":null}""",
            VerificationQuery.over21
        )
    }
}
