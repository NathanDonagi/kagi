package com.example.kagi.key

import java.security.MessageDigest
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * The phone's version of kagi_nano.ino: it holds a key (salted PBKDF2
 * commitments, never the facts) and answers queries with yes/no plus an HMAC
 * proof keyed with the device secret, exactly as the Nano does, so the servers
 * treat it like the Nano it replaces. The keys themselves are in DemoKeys.
 *
 *   SIGN   proof = HMAC(device_secret, "kagi-nano-sign-v1|<key id>|<site_id>|<nonce>")
 *   AUTH   proof = HMAC(device_secret, "kagi-nano-v1|<key id>|<scope>|<challenge>")
 *
 * Commitments: C = PBKDF2-HMAC-SHA256(SHA256(json(parts)), salt, iters, 32), stored as salt || C
 *   L1      ["L1","full_name",[first,last]]
 *   OVER t  ["OVER",t]      (random decoy bytes if under t)
 */
class PhoneKey(val keyId: String, deviceSecret: String, private val iters: Int, l1: String, over18: String, over21: String) {
    private val secret = deviceSecret.hexToBytes()
    private val commitments = mapOf("L1" to l1, "OVER18" to over18, "OVER21" to over21).mapValues { it.value.hexToBytes() }

    sealed interface Answer {
        data class Authenticated(val scope: String, val proof: String) : Answer
        data object Denied : Answer
    }

    /** SIGN <nonce> <site_id>: the unique sign-up answer. Reveals nothing about the person. */
    fun sign(nonce: String, siteId: String): String {
        require(validHex(nonce) && SITE.matches(siteId)) { "The server sent a malformed challenge." }
        return hmacHex("kagi-nano-sign-v1|$keyId|$siteId|$nonce")
    }

    /** AUTH <challenge> first_name=..;last_name=.. -> L1 */
    fun authName(first: String, last: String, challenge: String): Answer {
        val parts = try {
            "[\"L1\",\"full_name\",[\"${normName(first)}\",\"${normName(last)}\"]]"
        } catch (_: IllegalArgumentException) {
            return Answer.Denied            // like the Nano: no hint about what was wrong
        }
        return check("L1", parts, challenge)
    }

    /** AUTH <challenge> over=18|21 -> OVER18 / OVER21. Needs no name. */
    fun authOver(over: Int, challenge: String): Answer =
        if (over == 18 || over == 21) check("OVER$over", "[\"OVER\",$over]", challenge) else Answer.Denied

    private fun check(scope: String, parts: String, challenge: String): Answer {
        require(validHex(challenge)) { "The server sent a malformed challenge." }
        val c = commitments.getValue(scope)
        val pwd = MessageDigest.getInstance("SHA-256").digest(parts.toByteArray())
        val got = pbkdf2(pwd, c.copyOfRange(0, 32), iters)
        if (!MessageDigest.isEqual(got, c.copyOfRange(32, 64))) return Answer.Denied
        return Answer.Authenticated(scope, hmacHex("kagi-nano-v1|$keyId|$scope|$challenge"))
    }

    private fun hmacHex(msg: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(secret, "HmacSHA256"))
        return mac.doFinal(msg.toByteArray(Charsets.US_ASCII)).joinToString("") { "%02x".format(it) }
    }

    companion object {
        private val SITE = Regex("[a-z0-9.-]{1,64}")
        private val HEX = Regex("[0-9a-f]+")

        private fun validHex(s: String) = s.length in 1..64 && HEX.matches(s)

        /** Lowercase, trim, collapse whitespace; plain ASCII, 1-32 chars (same as the sketch). */
        fun normName(value: String): String {
            require(value.all { it == '\t' || it in ' '..'~' } && '"' !in value && '\\' !in value)
            val v = value.trim().split(Regex("[ \t]+")).filter { it.isNotEmpty() }.joinToString(" ")
            require(v.length in 1..32)
            return v.lowercase()
        }

        /** hashlib.pbkdf2_hmac("sha256", pwd, salt, iters, 32). Done by hand: the
         *  platform's PBKDF2 takes a char[] password, and ours is a binary digest. */
        private fun pbkdf2(pwd: ByteArray, salt: ByteArray, iters: Int): ByteArray {
            val mac = Mac.getInstance("HmacSHA256")
            mac.init(SecretKeySpec(pwd, "HmacSHA256"))
            var u = mac.doFinal(salt + byteArrayOf(0, 0, 0, 1))
            val out = u.copyOf()
            repeat(iters - 1) {
                u = mac.doFinal(u)
                for (j in out.indices) out[j] = (out[j].toInt() xor u[j].toInt()).toByte()
            }
            return out
        }

        private fun String.hexToBytes() = chunked(2).map { it.toInt(16).toByte() }.toByteArray()
    }
}
