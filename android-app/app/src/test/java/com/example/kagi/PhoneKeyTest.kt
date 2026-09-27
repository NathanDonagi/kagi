package com.example.kagi

import com.example.kagi.key.DemoKeys
import com.example.kagi.key.PhoneKey
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/** The pass key must answer exactly like the Arduino (what the servers check); the fail key must always fail. */
class PhoneKeyTest {
    private val pass = DemoKeys.PASS
    private val fail = DemoKeys.FAIL
    private val nonce = "93fdbf3028807a765e17a3b4254d5b31"

    // Expected proofs are computed the way central_server.py does, with the registry's secret.
    private fun serverProof(msg: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(hex(DemoKeys.PASS_SECRET), "HmacSHA256"))
        return mac.doFinal(msg.toByteArray()).joinToString("") { "%02x".format(it) }
    }

    private fun hex(s: String) = s.chunked(2).map { it.toInt(16).toByte() }.toByteArray()

    @Test fun passIsTheArduinoKey() = assertEquals("1b120e0f3e770faccbf4a262", pass.keyId)

    @Test fun passSignMatchesServer() = assertEquals(
        serverProof("kagi-nano-sign-v1|1b120e0f3e770faccbf4a262|blindgram|$nonce"), pass.sign(nonce, "blindgram"))

    @Test fun passIsOver18And21() {
        for (t in listOf(18, 21)) assertEquals(
            PhoneKey.Answer.Authenticated("OVER$t", serverProof("kagi-nano-v1|1b120e0f3e770faccbf4a262|OVER$t|$nonce")),
            pass.authOver(t, nonce))
    }

    @Test fun passConfirmsItsName() = assertEquals(
        PhoneKey.Answer.Authenticated("L1", serverProof("kagi-nano-v1|1b120e0f3e770faccbf4a262|L1|$nonce")),
        pass.authName("  NATHAN ", "donagi", nonce))

    @Test fun passDeniesOtherNames() {
        assertEquals(PhoneKey.Answer.Denied, pass.authName("Nathan", "Smith", nonce))
        assertEquals(PhoneKey.Answer.Denied, pass.authOver(25, nonce))
    }

    @Test fun failSaysNoToEverything() {
        assertEquals(PhoneKey.Answer.Denied, fail.authOver(18, nonce))
        assertEquals(PhoneKey.Answer.Denied, fail.authOver(21, nonce))
        assertEquals(PhoneKey.Answer.Denied, fail.authName("Nathan", "Donagi", nonce))
    }

    @Test fun failIsNotRegistered() {
        assertNotEquals(pass.keyId, fail.keyId)
        assertTrue(fail.sign(nonce, "blindgram") != pass.sign(nonce, "blindgram"))
    }
}
