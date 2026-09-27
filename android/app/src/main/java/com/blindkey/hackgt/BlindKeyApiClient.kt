package com.blindkey.hackgt

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URI
import java.util.UUID

class BlindKeyApiClient {
    companion object {
        private const val EXPECTED_API_VERSION = 3
        private const val CONNECT_TIMEOUT_MS = 5_000
        private const val READ_TIMEOUT_MS = 12_000
        private const val MAX_RESPONSE_BYTES = 64 * 1024
        private const val HEADER_REQUEST_ID = "X-Request-ID"
        private const val HEADER_API_VERSION = "X-BlindKey-API-Version"
        private const val HEADER_AUTHORITY_FINGERPRINT = "X-BlindKey-Authority-Fingerprint"
    }

    fun validateBaseUrl(value: String): String {
        val trimmed = value.trim().removeSuffix("/")
        require(trimmed.isNotEmpty()) { "Set the BlindKey backend URL first." }

        val uri = try { URI(trimmed) } catch (_: Exception) {
            throw IllegalArgumentException("Backend URL is invalid.")
        }
        require(uri.scheme == "http" || uri.scheme == "https") {
            "Backend URL must start with http:// or https://"
        }
        require(!uri.host.isNullOrBlank()) { "Backend URL must include a host." }
        require(uri.userInfo == null) { "Backend URL must not contain embedded credentials." }
        require(uri.query == null && uri.fragment == null) { "Backend URL must not contain a query or fragment." }
        require(uri.path.isNullOrBlank() || uri.path == "/") { "Backend URL must be a server origin, not a path." }
        require(uri.port == -1 || uri.port in 1..65535) { "Backend URL contains an invalid port." }
        return trimmed
    }

    suspend fun health(baseUrl: String): HealthResponse = withContext(Dispatchers.IO) {
        val base = validateBaseUrl(baseUrl)
        val requestId = UUID.randomUUID().toString()
        val connection = open("$base/health", "GET", requestId)
        try {
            val body = readResponse(connection, requestId, expectedAuthorityFingerprint = null)
            val json = JSONObject(body)
            val ok = json.optBoolean("ok", false)
            require(ok) { "BlindKey verifier reported unhealthy status." }
            val apiVersion = json.optInt("api_version", -1)
            require(apiVersion == EXPECTED_API_VERSION) {
                "Verifier API mismatch: app expects v$EXPECTED_API_VERSION but server reported v$apiVersion."
            }
            val fingerprint = json.optString("authority_fingerprint", "")
            require(fingerprint.matches(Regex("^[0-9a-f]{12}$"))) {
                "Verifier reported an invalid Authority fingerprint."
            }
            val headerFingerprint = connection.getHeaderField(HEADER_AUTHORITY_FINGERPRINT).orEmpty()
            require(headerFingerprint == fingerprint) {
                "Verifier Authority fingerprint header did not match the health response."
            }
            HealthResponse(apiVersion = apiVersion, authorityFingerprint = fingerprint)
        } finally {
            connection.disconnect()
        }
    }

    suspend fun verify(
        token: BlindKeyToken,
        query: VerificationQuery,
        baseUrl: String,
        expectedAuthorityFingerprint: String
    ): VerificationResponse = withContext(Dispatchers.IO) {
        val base = validateBaseUrl(baseUrl)
        require(expectedAuthorityFingerprint.matches(Regex("^[0-9a-f]{12}$"))) {
            "Test the backend connection before scanning a credential."
        }

        val requestId = UUID.randomUUID().toString()
        val body = JSONObject().apply {
            put("token", token.value)
            put("query", query.toJson())
        }.toString()

        val connection = open("$base/verify", "POST", requestId).apply {
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("Accept", "application/json")
            doOutput = true
            setFixedLengthStreamingMode(body.toByteArray(Charsets.UTF_8).size)
        }

        try {
            connection.outputStream.use { output ->
                output.write(body.toByteArray(Charsets.UTF_8))
            }
            val responseBody = readResponse(
                connection,
                requestId,
                expectedAuthorityFingerprint = expectedAuthorityFingerprint
            )
            parseVerificationResponse(responseBody, query)
        } finally {
            connection.disconnect()
        }
    }

    internal fun parseVerificationResponse(body: String, query: VerificationQuery): VerificationResponse {
        val json = try {
            JSONObject(body)
        } catch (_: Exception) {
            throw IllegalStateException("Verifier returned malformed JSON.")
        }
        val verified = json.optBoolean("verified", false)
        val scope = json.optString("scope").takeIf { it.isNotBlank() && it != "null" }
        val error = json.optString("error").takeIf { it.isNotBlank() && it != "null" }

        if (verified) {
            require(error == null) { "Verifier returned an inconsistent success response." }
            require(scope == query.expectedScope) {
                "Verifier proved an unexpected scope (${scope ?: "missing"}); expected ${query.expectedScope}."
            }
        } else {
            require(scope == null) { "Verifier returned a scope for a failed verification." }
        }

        return VerificationResponse(verified = verified, scope = scope, error = error)
    }

    private fun open(url: String, method: String, requestId: String): HttpURLConnection {
        return (URI(url).toURL().openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = CONNECT_TIMEOUT_MS
            readTimeout = READ_TIMEOUT_MS
            useCaches = false
            instanceFollowRedirects = false
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Cache-Control", "no-store")
            setRequestProperty(HEADER_REQUEST_ID, requestId)
        }
    }

    private fun readResponse(
        connection: HttpURLConnection,
        requestId: String,
        expectedAuthorityFingerprint: String?
    ): String {
        val code = connection.responseCode

        val echoedRequestId = connection.getHeaderField(HEADER_REQUEST_ID)
        require(echoedRequestId == requestId) { "Verifier response could not be correlated to this request." }

        val apiVersionHeader = connection.getHeaderField(HEADER_API_VERSION)?.toIntOrNull()
        require(apiVersionHeader == EXPECTED_API_VERSION) {
            "Verifier API header mismatch."
        }

        expectedAuthorityFingerprint?.let { expected ->
            val actual = connection.getHeaderField(HEADER_AUTHORITY_FINGERPRINT).orEmpty()
            require(actual == expected) {
                "Verifier Authority changed. Test the backend connection again before scanning."
            }
        }

        val contentType = connection.contentType.orEmpty().lowercase()
        require(contentType.startsWith("application/json")) {
            "Verifier returned an unexpected content type."
        }

        val contentLength = connection.contentLengthLong
        require(contentLength < 0 || contentLength <= MAX_RESPONSE_BYTES) {
            "Verifier response was unexpectedly large."
        }

        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val body = stream?.use { input -> readBoundedUtf8(input) }.orEmpty()

        if (code !in 200..299) {
            val detail = try {
                val json = JSONObject(body)
                json.optString("detail").takeIf { it.isNotBlank() } ?: "HTTP $code"
            } catch (_: Exception) {
                "HTTP $code"
            }
            throw IllegalStateException("Verifier request failed: $detail")
        }
        return body
    }

    private fun readBoundedUtf8(input: java.io.InputStream): String {
        val buffered = BufferedInputStream(input)
        val out = ByteArrayOutputStream()
        val buffer = ByteArray(4096)
        var total = 0
        while (true) {
            val read = buffered.read(buffer)
            if (read < 0) break
            total += read
            require(total <= MAX_RESPONSE_BYTES) { "Verifier response was unexpectedly large." }
            out.write(buffer, 0, read)
        }
        return out.toString(Charsets.UTF_8.name())
    }
}
