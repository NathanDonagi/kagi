package com.blindkey.hackgt

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.util.UUID

class VerificationViewModel(application: Application) : AndroidViewModel(application) {
    private val config = AppConfig(application)
    private val api = BlindKeyApiClient()

    private val _state = MutableStateFlow<VerificationState>(VerificationState.Idle)
    val state: StateFlow<VerificationState> = _state.asStateFlow()

    private val _lastDiagnostic = MutableStateFlow<NfcTagDiagnostic?>(null)
    val lastDiagnostic: StateFlow<NfcTagDiagnostic?> = _lastDiagnostic.asStateFlow()

    private val _backendUrl = MutableStateFlow(config.backendBaseUrl)
    val backendUrl: StateFlow<String> = _backendUrl.asStateFlow()

    private val _showDebugTools = MutableStateFlow(config.showDebugTools)
    val showDebugTools: StateFlow<Boolean> = _showDebugTools.asStateFlow()

    private val _backendTestMessage = MutableStateFlow(initialBackendStatus())
    val backendTestMessage: StateFlow<String?> = _backendTestMessage.asStateFlow()

    private val _isTestingBackend = MutableStateFlow(false)
    val isTestingBackend: StateFlow<Boolean> = _isTestingBackend.asStateFlow()

    private var currentOperation = UUID.randomUUID()
    private var verifyJob: Job? = null
    private var backendTestJob: Job? = null
    private var activeNfcService: AndroidNfcService? = null

    fun selectQuery(query: VerificationQuery) {
        invalidateOperation()
        _lastDiagnostic.value = null
        _state.value = VerificationState.QueryReady(query)
    }

    fun startScan(nfcService: AndroidNfcService) {
        val query = _state.value.query ?: return
        val normalizedUrl = try {
            api.validateBaseUrl(_backendUrl.value)
        } catch (e: Exception) {
            _state.value = VerificationState.Error(query, e.message ?: "Backend URL is invalid.")
            return
        }

        val trustedFingerprint = config.trustedFingerprintFor(normalizedUrl)
        if (trustedFingerprint == null) {
            _state.value = VerificationState.Error(
                query,
                "Test the backend connection in Settings before scanning. This pins the expected BlindKey Authority for the demo."
            )
            return
        }

        if (!nfcService.isAvailable) {
            _state.value = VerificationState.Error(
                query,
                nfcService.unavailableReason ?: "NFC is unavailable or disabled on this Android device."
            )
            return
        }

        invalidateOperation()
        activeNfcService = nfcService
        val operation = UUID.randomUUID()
        currentOperation = operation
        _lastDiagnostic.value = null
        _state.value = VerificationState.Scanning(query)

        nfcService.startScan { result ->
            handleNfcResult(result, query, operation, trustedFingerprint)
        }
    }

    private fun handleNfcResult(
        result: NfcScanResult,
        query: VerificationQuery,
        operation: UUID,
        trustedFingerprint: String
    ) {
        if (currentOperation != operation || _state.value.query != query) return

        when (result) {
            is NfcScanResult.Token -> {
                _lastDiagnostic.value = result.diagnostic
                _state.value = VerificationState.TagDetected(query, result.diagnostic)
                verify(result.token, query, operation, trustedFingerprint)
            }

            is NfcScanResult.TagWithoutToken -> {
                _lastDiagnostic.value = result.diagnostic
                _state.value = VerificationState.Error(
                    query,
                    "NFC tag detected, but no BlindKey token was found. Write one short bk1:... value as a single NDEF Text record."
                )
            }

            is NfcScanResult.Failed -> {
                _state.value = VerificationState.Error(query, result.message)
            }
        }
    }

    private fun verify(
        token: BlindKeyToken,
        query: VerificationQuery,
        operation: UUID,
        trustedFingerprint: String
    ) {
        verifyJob?.cancel()
        _state.value = VerificationState.Verifying(query)
        val baseUrl = _backendUrl.value

        verifyJob = viewModelScope.launch {
            try {
                val response = api.verify(
                    token = token,
                    query = query,
                    baseUrl = baseUrl,
                    expectedAuthorityFingerprint = trustedFingerprint
                )
                if (currentOperation != operation || _state.value.query != query) return@launch

                if (response.verified) {
                    _state.value = VerificationState.Verified(query, response.scope!!)
                } else if (response.error != null) {
                    val message = when (response.error) {
                        "invalid_credential" -> "Resolved credential is invalid, expired, or not issued by this BlindKey Authority."
                        "invalid_query" -> "The verifier rejected this verification request."
                        "unknown_token" -> "This NFC token is not registered with the BlindKey demo backend."
                        else -> "Verification could not be completed (${response.error})."
                    }
                    _state.value = VerificationState.Error(query, message)
                } else {
                    _state.value = VerificationState.Denied(query)
                }
            } catch (_: CancellationException) {
                // Deliberate cancellation during reset/retry/lifecycle changes.
            } catch (e: Exception) {
                if (currentOperation != operation || _state.value.query != query) return@launch
                _state.value = VerificationState.Error(
                    query,
                    e.message ?: "Unable to contact the BlindKey verifier."
                )
            }
        }
    }

    fun retry() {
        val query = _state.value.query
        invalidateOperation()
        _lastDiagnostic.value = null
        _state.value = if (query == null) VerificationState.Idle else VerificationState.QueryReady(query)
    }

    fun reset() {
        invalidateOperation()
        _lastDiagnostic.value = null
        _state.value = VerificationState.Idle
    }

    fun cancelActiveScanForLifecycle() {
        val current = _state.value
        if (current is VerificationState.Scanning) {
            val query = current.query
            invalidateOperation()
            _state.value = VerificationState.QueryReady(query)
        }
    }

    private fun invalidateOperation() {
        currentOperation = UUID.randomUUID()
        activeNfcService?.cancel()
        activeNfcService = null
        verifyJob?.cancel()
        verifyJob = null
    }

    fun updateBackendUrl(value: String) {
        val trimmed = value.trim()
        val oldNormalized = runCatching { api.validateBaseUrl(_backendUrl.value) }.getOrNull()
        val newNormalized = runCatching { api.validateBaseUrl(trimmed) }.getOrNull()

        _backendUrl.value = trimmed
        config.backendBaseUrl = trimmed

        if (oldNormalized != newNormalized || config.trustedBackendUrl != newNormalized) {
            config.clearBackendTrust()
        }
        _backendTestMessage.value = null
    }

    fun updateDebugTools(enabled: Boolean) {
        _showDebugTools.value = enabled
        config.showDebugTools = enabled
    }

    fun testBackend() {
        backendTestJob?.cancel()
        val baseUrl = _backendUrl.value
        _isTestingBackend.value = true
        _backendTestMessage.value = null

        backendTestJob = viewModelScope.launch {
            try {
                val normalizedUrl = api.validateBaseUrl(baseUrl)
                val health = api.health(normalizedUrl)
                config.trustBackend(normalizedUrl, health.authorityFingerprint)
                _backendTestMessage.value =
                    "Connected ✓  API v${health.apiVersion}  Authority ${health.authorityFingerprint}"
            } catch (_: CancellationException) {
                // Ignore.
            } catch (e: Exception) {
                config.clearBackendTrust()
                _backendTestMessage.value = e.message ?: "Backend connection failed."
            } finally {
                _isTestingBackend.value = false
            }
        }
    }

    fun debugForceVerified() {
        val query = _state.value.query ?: return
        invalidateOperation()
        _state.value = VerificationState.Verified(query, query.expectedScope)
    }

    fun debugForceDenied() {
        val query = _state.value.query ?: return
        invalidateOperation()
        _state.value = VerificationState.Denied(query)
    }

    private fun initialBackendStatus(): String? {
        val url = runCatching { api.validateBaseUrl(config.backendBaseUrl) }.getOrNull() ?: return null
        val fingerprint = config.trustedFingerprintFor(url) ?: return null
        return "Trusted backend ✓  Authority $fingerprint"
    }

    override fun onCleared() {
        invalidateOperation()
        backendTestJob?.cancel()
        super.onCleared()
    }
}
