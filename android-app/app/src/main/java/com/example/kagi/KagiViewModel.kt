package com.example.kagi

import android.app.Application
import android.os.SystemClock
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.kagi.bridge.BluetoothLink
import com.example.kagi.bridge.BridgeClient
import com.example.kagi.bridge.NoPermission
import com.example.kagi.bridge.Reply
import com.example.kagi.bridge.TcpLink
import com.example.kagi.key.DemoKeys
import com.example.kagi.key.PhoneKey
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject
import java.io.IOException

/** A looked-up code: what's being asked, and what the key needs to answer it. */
data class Challenge(
    val code: String,
    val kind: Kind,
    val siteId: String = "",
    val siteName: String = "",
    val nonce: String? = null,          // absent from challenge_site.py before the kagi-bt-1 change
    val over: Int = 0,
    val firstName: String = "",
    val lastName: String = "",
    val expiresAt: Long,                // SystemClock.elapsedRealtime()
) {
    enum class Kind { NAME_CHECK, UNIQUE_SIGNUP, AGE_CHECK }
}

sealed interface Phase {
    data class Tap(val note: String? = null) : Phase
    data object Checking : Phase
    data object Sending : Phase
    data class Done(val ok: Boolean, val headline: String, val message: String, val canRetry: Boolean = false) : Phase
}

sealed interface Screen {
    data class Code(val busy: Boolean = false, val error: String = "") : Screen
    data class Auth(val ch: Challenge, val phase: Phase) : Screen
    data object Settings : Screen
}

/** The two demo tags. Each stands for a key the phone holds (DemoKeys). */
enum class Tag(val key: PhoneKey) { PASS(DemoKeys.PASS), FAIL(DemoKeys.FAIL) }

class KagiViewModel(app: Application) : AndroidViewModel(app) {
    private val settingsStore = Settings.Store(app)
    val bridge = BridgeClient(viewModelScope) { s, onSocket ->
        if (s.useTcp) TcpLink() else BluetoothLink.open(app, s.pcAddress!!, s.rfcommChannel, onSocket)
    }

    private val _screen = MutableStateFlow<Screen>(Screen.Code())
    val screen: StateFlow<Screen> = _screen
    private val _settings = MutableStateFlow(settingsStore.load())
    val settings: StateFlow<Settings> = _settings

    /** Which tag Settings is waiting to learn, if any. */
    private val _enrolling = MutableStateFlow<Tag?>(null)
    val enrolling: StateFlow<Tag?> = _enrolling

    private var flowJob: Job? = null
    private var tapWaiter: CompletableDeferred<Tag>? = null
    private var bridgeSettings: Settings? = null

    init {
        restartBridge()
    }

    fun restartBridge() {
        bridgeSettings = _settings.value
        bridge.start(_settings.value)
    }

    // ---------- screen 1: enter code ----------

    fun showCodeScreen() {
        flowJob?.cancel()
        tapWaiter = null
        _enrolling.value = null
        // Leaving Settings: reconnect if the PC or transport changed.
        val s = _settings.value
        val b = bridgeSettings
        if (b == null || b.pcAddress != s.pcAddress || b.rfcommChannel != s.rfcommChannel || b.useTcp != s.useTcp) {
            restartBridge()
        }
        _screen.value = Screen.Code()
    }

    fun submitCode(text: String) {
        val code = text.filter(Char::isDigit)
        if (code.length != 8 && code.length != 12) {
            _screen.value = Screen.Code(error = "The code is 8 or 12 digits.")
            return
        }
        _screen.value = Screen.Code(busy = true)
        flowJob?.cancel()
        flowJob = viewModelScope.launch {
            val ch = try {
                if (code.length == 12) lookupCentral(code) else lookupChallenge(code)
            } catch (e: Problem) {
                _screen.value = Screen.Code(error = e.message!!)
                return@launch
            }
            authenticate(ch)
        }
    }

    private class Problem(message: String) : Exception(message)

    private suspend fun call(target: String, method: String, path: String, body: JSONObject? = null): Reply =
        try {
            bridge.request(target, method, path, body)
        } catch (e: IOException) {
            throw Problem(e.message ?: "Not connected to the PC.")
        }

    private fun serverSaid(r: Reply) = "The server said: ${r.error.trimEnd('.')}."

    private fun expiresAt(body: JSONObject) =
        SystemClock.elapsedRealtime() + body.optInt("expires_in", 300).coerceAtLeast(0) * 1000L

    private fun JSONObject.need(name: String): String =
        optString(name).ifEmpty { throw Problem("The server sent an answer this app doesn't understand.") }

    /** communication.md §3.1: 12-digit codes from central_server.py. */
    private suspend fun lookupCentral(code: String): Challenge {
        val r = call("central", "GET", "/api/challenges/$code")
        if (r.status == 404) throw Problem("That code doesn't exist, has expired or was already used.")
        if (r.status != 200) throw Problem(serverSaid(r))
        val b = r.body
        val kind = when (b.optString("type")) {
            "unique_signup" -> Challenge.Kind.UNIQUE_SIGNUP
            "age_check" -> Challenge.Kind.AGE_CHECK
            else -> throw Problem("This app doesn't know that kind of request.")
        }
        val over = if (kind == Challenge.Kind.AGE_CHECK) b.optInt("over", 0) else 0
        if (kind == Challenge.Kind.AGE_CHECK && over <= 0) throw Problem("This app doesn't know that kind of request.")
        return Challenge(
            code, kind, siteId = b.need("site_id"), siteName = b.need("site_name"), nonce = b.need("nonce"),
            over = over, expiresAt = expiresAt(b),
        )
    }

    /** communication.md §3.4: 8-digit codes from challenge_site.py. */
    private suspend fun lookupChallenge(code: String): Challenge {
        val r = call("challenge", "GET", "/api/challenges/$code")
        if (r.status == 404) throw Problem("That code doesn't exist or has expired.")
        if (r.status != 200) throw Problem(serverSaid(r))
        val b = r.body
        if (b.optString("status") != "waiting") throw Problem("That code has already been used.")
        return Challenge(
            code, Challenge.Kind.NAME_CHECK, nonce = b.optString("nonce").ifEmpty { null },
            firstName = b.need("first_name"), lastName = b.need("last_name"), expiresAt = expiresAt(b),
        )
    }

    // ---------- screen 2: authenticate ----------

    fun retry() {
        val s = _screen.value as? Screen.Auth ?: return
        authenticate(s.ch)
    }

    private fun authenticate(ch: Challenge) {
        flowJob?.cancel()
        _screen.value = Screen.Auth(ch, Phase.Tap())
        flowJob = viewModelScope.launch {
            val done = try {
                when (ch.kind) {
                    Challenge.Kind.UNIQUE_SIGNUP -> signupFlow(ch)
                    Challenge.Kind.AGE_CHECK -> ageFlow(ch)
                    Challenge.Kind.NAME_CHECK -> nameCheckFlow(ch)
                }
            } catch (e: Problem) {
                Phase.Done(false, "Not verified", e.message!!, canRetry = true)
            }
            setPhase(done)
        }
    }

    private fun setPhase(p: Phase) {
        val s = _screen.value as? Screen.Auth ?: return
        _screen.value = s.copy(phase = p)
    }

    private val expired = Phase.Done(false, "Code expired", "Get a new code and try again.")

    /** Waits for a known tag (or null if the code expires first), then shows "checking". */
    private suspend fun awaitTap(ch: Challenge): PhoneKey? {
        val waiter = CompletableDeferred<Tag>()
        tapWaiter = waiter
        early?.let { (id, at) -> if (SystemClock.elapsedRealtime() - at < 3000) deliver(waiter, id) }
        early = null
        // Recording mode: the pass key answers by itself unless a real tag is tapped first.
        val auto = if (_settings.value.autoVerify) viewModelScope.launch {
            delay(3000)
            waiter.complete(Tag.PASS)
        } else null
        val tag = try {
            withTimeoutOrNull(ch.expiresAt - SystemClock.elapsedRealtime()) { waiter.await() }
        } finally {
            auto?.cancel()
        }
        tapWaiter = null
        if (tag != null) {
            setPhase(Phase.Checking)
            delay(700)                      // long enough to see that the key was read
        }
        return tag?.key
    }

    private suspend fun ask(q: () -> PhoneKey.Answer): PhoneKey.Answer = try {
        withContext(Dispatchers.Default) { q() }
    } catch (e: IllegalArgumentException) {
        throw Problem(e.message ?: "The server sent a malformed challenge.")
    }

    /** §3.2: the key signs the server's nonce; the server says new or existing. */
    private suspend fun signupFlow(ch: Challenge): Phase {
        val key = awaitTap(ch) ?: return expired
        val proof = try {
            key.sign(ch.nonce!!, ch.siteId)
        } catch (e: IllegalArgumentException) {
            throw Problem(e.message!!)
        }
        setPhase(Phase.Sending)
        val r = call("central", "POST", "/api/challenges/${ch.code}/response",
            JSONObject().put("key_id", key.keyId).put("proof", proof))
        if (r.status != 200) return Phase.Done(false, "Not verified", serverSaid(r), canRetry = r.status == 400)
        return when (r.body.optString("result")) {
            "new" -> Phase.Done(true, "You're in", "Go back to ${ch.siteName} to finish signing up.")
            "existing" -> Phase.Done(false, "Already signed up",
                "You already have a ${ch.siteName} account. It allows one per person.")
            else -> throw Problem("The server sent an answer this app doesn't understand.")
        }
    }

    /** §3.3: the key answers "over N?" by itself; only a yes produces a proof. */
    private suspend fun ageFlow(ch: Challenge): Phase {
        val key = awaitTap(ch) ?: return expired
        val answer = ask { key.authOver(ch.over, ch.nonce!!) }
        setPhase(Phase.Sending)
        val body = if (answer is PhoneKey.Answer.Authenticated && answer.scope == "OVER${ch.over}") {
            JSONObject().put("key_id", key.keyId).put("proof", answer.proof)
        } else {
            JSONObject().put("declined", true)
        }
        val r = call("central", "POST", "/api/challenges/${ch.code}/response", body)
        if (r.status != 200) return Phase.Done(false, "Not verified", serverSaid(r), canRetry = r.status == 400)
        return when (r.body.optString("result")) {
            "verified" -> Phase.Done(true, "Verified ${ch.over}+",
                "${ch.siteName} now knows you're ${ch.over} or over. Nothing else.")
            "declined" -> Phase.Done(false, "Not verified", "Your key says you're not ${ch.over} or over.")
            else -> throw Problem("The server sent an answer this app doesn't understand.")
        }
    }

    /** §3.4: the key checks the name the host typed. */
    private suspend fun nameCheckFlow(ch: Challenge): Phase {
        val key = awaitTap(ch) ?: return expired
        // challenge_site.py before kagi-bt-1 has no nonce and takes {"verified": bool};
        // the key still does the real check, over a challenge of our own.
        val challenge = ch.nonce ?: "00".repeat(16)
        val answer = ask { key.authName(ch.firstName, ch.lastName, challenge) }
        val yes = answer is PhoneKey.Answer.Authenticated && answer.scope == "L1"
        setPhase(Phase.Sending)
        val body = when {
            ch.nonce == null -> JSONObject().put("verified", yes)
            answer is PhoneKey.Answer.Authenticated && yes -> JSONObject().put("key_id", key.keyId).put("proof", answer.proof)
            else -> JSONObject().put("declined", true)
        }
        val r = call("challenge", "POST", "/api/challenges/${ch.code}/result", body)
        when (r.status) {
            200 -> {}
            409 -> return Phase.Done(false, "Not verified", "That code was already answered or has expired.")
            else -> return Phase.Done(false, "Not verified", serverSaid(r), canRetry = r.status == 400)
        }
        val verified = when (r.body.optString("status")) {
            "verified" -> true
            "failed" -> false
            "" -> if (ch.nonce == null && r.body.optBoolean("ok")) yes
                  else throw Problem("The server sent an answer this app doesn't understand.")
            else -> throw Problem("The server sent an answer this app doesn't understand.")
        }
        return if (verified) Phase.Done(true, "Verified", "Your key confirmed this name.")
        else Phase.Done(false, "Not verified", "This key doesn't belong to that person.")
    }

    // ---------- NFC ----------

    /** The last tag tapped while nothing was waiting: a tap made just before the
     *  "tap your key" screen appears (e.g. during "Looking up...") still counts. */
    private var early: Pair<String, Long>? = null

    /** A tag was read (any thread). Routes it to Settings or to the waiting check. */
    fun onTag(id: String, tech: Int) = viewModelScope.launch(Dispatchers.Main) {
        val s = _settings.value
        _enrolling.value?.let { which ->
            updateSettings(
                if (which == Tag.PASS) {
                    s.copy(passTag = id, passTech = tech, failTag = s.failTag.takeIf { it != id })
                } else {
                    s.copy(failTag = id, failTech = tech, passTag = s.passTag.takeIf { it != id })
                }
            )
            _enrolling.value = null
            return@launch
        }
        val waiter = tapWaiter
        if (waiter == null) {
            early = id to SystemClock.elapsedRealtime()
            return@launch
        }
        deliver(waiter, id)
    }

    private fun deliver(waiter: CompletableDeferred<Tag>, id: String) {
        val s = _settings.value
        when (id) {
            s.passTag -> waiter.complete(Tag.PASS)
            s.failTag -> waiter.complete(Tag.FAIL)
            else -> setPhase(Phase.Tap(
                if (s.passTag == null && s.failTag == null) "No tags are registered yet. Add them in Settings."
                else "That tag isn't one of your kagi keys."
            ))
        }
    }

    fun simulateTap(tag: Tag) {
        tapWaiter?.complete(tag)
    }

    // ---------- Settings ----------

    fun openSettings() {
        flowJob?.cancel()
        tapWaiter = null
        _screen.value = Screen.Settings
    }

    fun updateSettings(s: Settings) {
        _settings.value = s
        settingsStore.save(s)
    }

    fun bondedDevices(): List<Pair<String, String>>? = try {
        BluetoothLink.bonded(getApplication())
    } catch (_: NoPermission) {
        null
    }

    fun enroll(tag: Tag?) {
        _enrolling.value = tag
    }
}
