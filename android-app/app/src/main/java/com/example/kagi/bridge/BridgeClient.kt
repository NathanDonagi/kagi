package com.example.kagi.bridge

import com.example.kagi.Settings
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.json.JSONException
import org.json.JSONObject
import java.io.BufferedReader
import java.io.Closeable
import java.io.IOException
import java.io.Writer
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger
import kotlin.coroutines.cancellation.CancellationException

/** One reply from the bridge: the HTTP status and the server's JSON. */
data class Reply(val status: Int, val body: JSONObject) {
    /** The server's {"error": ...}, fine to show the user. */
    val error: String get() = body.optString("error").ifBlank { "status $status" }
}

sealed interface BridgeState {
    data object NotSetUp : BridgeState
    data object NoPermission : BridgeState
    data class Connecting(val name: String) : BridgeState
    data class Connected(val name: String) : BridgeState
    data class Reconnecting(val name: String, val why: String) : BridgeState
}

/**
 * The kagi-bt-1 client (communication.md). Keeps one connection to
 * bluetooth_bridge.py open, reconnecting with backoff, and matches responses
 * to requests by id. Nothing here logs request contents.
 */
class BridgeClient(
    private val scope: CoroutineScope,
    /** Opens the link (blocking); the callback gets each socket before it connects, so it can be cancelled. */
    private val open: (Settings, onSocket: (Closeable) -> Unit) -> Link,
) {
    private val _state = MutableStateFlow<BridgeState>(BridgeState.NotSetUp)
    val state: StateFlow<BridgeState> = _state

    private val nextId = AtomicInteger(1)
    private val pending = ConcurrentHashMap<Int, CompletableDeferred<Reply>>()
    private val writeLock = Mutex()
    private var job: Job? = null
    @Volatile private var opening: Closeable? = null
    @Volatile private var writer: Writer? = null

    fun start(settings: Settings) {
        job?.cancel()
        closeQuietly(opening)
        link?.let(::dropConnection)
        job = scope.launch(Dispatchers.IO) { run(settings) }
    }

    /** Sends one request and waits for its response. IOException if the PC isn't there. */
    suspend fun request(target: String, method: String, path: String, body: JSONObject? = null): Reply {
        val l = link
        val out = writer ?: throw IOException(
            if (_state.value is BridgeState.NotSetUp) "Choose your PC in Settings first." else "Not connected to the PC."
        )
        val id = nextId.getAndIncrement()
        val msg = JSONObject().put("id", id).put("target", target).put("method", method).put("path", path)
        if (method == "POST") msg.put("body", body ?: JSONObject())
        val reply = CompletableDeferred<Reply>()
        pending[id] = reply
        try {
            withContext(Dispatchers.IO) {
                writeLock.withLock {
                    out.write(msg.toString() + "\n")
                    out.flush()
                }
            }
            return withTimeout(35_000) { reply.await() }
        } catch (_: TimeoutCancellationException) {
            throw IOException("The PC didn't answer.")
        } catch (e: IOException) {
            l?.let(::dropConnection)
            throw IOException("Lost the connection to the PC.", e)
        } finally {
            pending.remove(id)
        }
    }

    @Volatile private var link: Link? = null

    private suspend fun run(settings: Settings) {
        val me = currentCoroutineContext()[Job]!!
        val label = if (settings.useTcp) "127.0.0.1:8766" else settings.pcName ?: "PC"
        if (!settings.useTcp && settings.pcAddress == null) {
            _state.value = BridgeState.NotSetUp
            return
        }
        var backoff = 1000L
        _state.value = BridgeState.Connecting(label)
        while (true) {
            var l: Link? = null
            val why = try {
                l = open(settings) { s ->
                    opening = s
                    if (!me.isActive) throw IOException("cancelled")
                }
                opening = null
                if (!me.isActive) return
                link = l
                serve(l)                    // returns when the connection drops
                backoff = 1000L
                "Lost the connection."
            } catch (e: CancellationException) {
                throw e
            } catch (_: NoPermission) {
                _state.value = BridgeState.NoPermission
                return
            } catch (e: Exception) {
                e.message ?: "Couldn't connect."
            } finally {
                l?.let(::dropConnection)
            }
            if (!me.isActive) return
            _state.value = BridgeState.Reconnecting(label, why)
            delay(backoff)
            backoff = (backoff * 2).coerceAtMost(10_000L)
        }
    }

    /** Hello, then the reader loop plus a keep-alive ping every 15 s. */
    private suspend fun serve(l: Link) {
        val reader: BufferedReader = l.input.bufferedReader(Charsets.UTF_8)
        // A blocking read ignores coroutine timeouts, so close the socket if hello doesn't come.
        val watchdog = scope.launch {
            delay(10_000)
            closeQuietly(l)
        }
        val hello = try {
            reader.readLine()
        } finally {
            watchdog.cancel()
        } ?: throw IOException("The bridge closed the connection.")
        val h = try {
            JSONObject(hello)
        } catch (_: JSONException) {
            throw IOException("That isn't a kagi bridge.")
        }
        if (h.optString("type") != "hello" || h.optString("protocol") != "kagi-bt-1") {
            throw IOException("The bridge speaks a different protocol (${h.optString("protocol")}).")
        }
        writer = l.output.bufferedWriter(Charsets.UTF_8)
        _state.value = BridgeState.Connected(l.name)

        val pinger = scope.launch {
            while (true) {
                delay(15_000)
                if (pending.isEmpty()) {
                    try {
                        request("bridge", "GET", "/ping")
                    } catch (_: IOException) {
                        dropConnection(l)
                        return@launch
                    }
                }
            }
        }
        try {
            while (true) {
                val line = reader.readLine() ?: break
                val o = try {
                    JSONObject(line)
                } catch (_: JSONException) {
                    continue
                }
                if (o.optString("type") != "response") continue
                val id = o.opt("id") as? Number ?: continue       // null id: a request it couldn't parse
                val body = o.optJSONObject("body") ?: JSONObject()
                pending[id.toInt()]?.complete(Reply(o.optInt("status", 0), body))
            }
        } catch (_: IOException) {
            // closed under us; reconnect below
        } finally {
            pinger.cancel()
        }
    }

    /** Closes [l] and fails everything waiting on it, if it's still the current link. */
    private fun dropConnection(l: Link) {
        closeQuietly(l)
        synchronized(this) {
            if (link !== l) return
            link = null
            writer = null
        }
        val err = IOException("Lost the connection to the PC.")
        pending.values.forEach { it.completeExceptionally(err) }
    }

    private fun closeQuietly(c: Closeable?) {
        try {
            c?.close()
        } catch (_: IOException) {
        }
    }
}
