package com.blindkey.hackgt

import org.json.JSONObject

data class VerificationQuery(
    val id: String,
    val label: String,
    val humanQuestion: String,
    val expectedScope: String,
    val payload: Map<String, Any>
) {
    fun toJson(): JSONObject = JSONObject().apply {
        payload.forEach { (key, value) -> put(key, value) }
    }

    companion object {
        val verifyIdentity = VerificationQuery(
            id = "verify-identity",
            label = "Verify Identity",
            humanQuestion = "Is this Nathan Donagi?",
            expectedScope = "L1",
            payload = mapOf("first_name" to "Nathan", "last_name" to "Donagi")
        )

        val over18 = VerificationQuery(
            id = "over-18",
            label = "Over 18",
            humanQuestion = "Is Nathan Donagi over 18?",
            expectedScope = "OVER18",
            payload = mapOf("first_name" to "Nathan", "last_name" to "Donagi", "over" to 18)
        )

        val over21 = VerificationQuery(
            id = "over-21",
            label = "Over 21",
            humanQuestion = "Is Nathan Donagi over 21?",
            expectedScope = "OVER21",
            payload = mapOf("first_name" to "Nathan", "last_name" to "Donagi", "over" to 21)
        )

        val highSecurity = VerificationQuery(
            id = "high-security",
            label = "High-Security Verification",
            humanQuestion = "Does this identity pass high-security verification?",
            expectedScope = "L2",
            payload = mapOf(
                "first_name" to "Nathan",
                "last_name" to "Donagi",
                "age" to 22,
                "ssn" to "123-45-6789",
                "pin" to "4821"
            )
        )

        val primaryDemoCases = listOf(verifyIdentity, over18, over21)
        val advancedDemoCases = listOf(highSecurity)
    }
}

enum class TrafficLight { RED, YELLOW, GREEN }

sealed interface VerificationState {
    val query: VerificationQuery?
    val trafficLight: TrafficLight
    val statusText: String

    data object Idle : VerificationState {
        override val query: VerificationQuery? = null
        override val trafficLight = TrafficLight.YELLOW
        override val statusText = "Select a verification request"
    }

    data class QueryReady(override val query: VerificationQuery) : VerificationState {
        override val trafficLight = TrafficLight.YELLOW
        override val statusText = "READY TO VERIFY"
    }

    data class Scanning(override val query: VerificationQuery) : VerificationState {
        override val trafficLight = TrafficLight.YELLOW
        override val statusText = "WAITING FOR BLINDKEY"
    }

    data class TagDetected(
        override val query: VerificationQuery,
        val diagnostic: NfcTagDiagnostic
    ) : VerificationState {
        override val trafficLight = TrafficLight.YELLOW
        override val statusText = "CREDENTIAL DETECTED"
    }

    data class Verifying(override val query: VerificationQuery) : VerificationState {
        override val trafficLight = TrafficLight.YELLOW
        override val statusText = "VERIFYING…"
    }

    data class Verified(
        override val query: VerificationQuery,
        val scope: String
    ) : VerificationState {
        override val trafficLight = TrafficLight.GREEN
        override val statusText = "VERIFIED"
    }

    data class Denied(override val query: VerificationQuery) : VerificationState {
        override val trafficLight = TrafficLight.RED
        override val statusText = "DENIED"
    }

    data class Error(
        override val query: VerificationQuery,
        val message: String
    ) : VerificationState {
        override val trafficLight = TrafficLight.YELLOW
        override val statusText = "UNABLE TO VERIFY"
    }
}

data class VerificationResponse(
    val verified: Boolean,
    val scope: String?,
    val error: String?
)

data class HealthResponse(
    val apiVersion: Int,
    val authorityFingerprint: String
)
