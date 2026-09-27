package com.example.kagi.bridge

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothSocket
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import java.io.Closeable
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.util.UUID

/** A byte stream to bluetooth_bridge.py: Bluetooth RFCOMM, or TCP for debugging. */
interface Link : Closeable {
    val name: String
    val input: InputStream
    val output: OutputStream
}

val KAGI_UUID: UUID = UUID.fromString("083d2893-6eab-4283-b12c-cdf0771acb72")

class NoPermission : IOException("Bluetooth permission needed.")

fun hasBluetoothPermission(context: Context) = Build.VERSION.SDK_INT < Build.VERSION_CODES.S ||
    context.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED

class TcpLink(host: String = "127.0.0.1", port: Int = 8766) : Link {
    private val socket = Socket().apply { connect(InetSocketAddress(host, port), 5000) }
    override val name = "$host:$port"
    override val input: InputStream = socket.getInputStream()
    override val output: OutputStream = socket.getOutputStream()
    override fun close() = socket.close()
}

@SuppressLint("MissingPermission")          // checked in open()
class BluetoothLink private constructor(private val socket: BluetoothSocket, override val name: String) : Link {
    override val input: InputStream = socket.inputStream
    override val output: OutputStream = socket.outputStream
    override fun close() = socket.close()

    companion object {
        /** Paired devices as (name, MAC), for choosing the PC. */
        fun bonded(context: Context): List<Pair<String, String>> {
            if (!hasBluetoothPermission(context)) throw NoPermission()
            val adapter = context.getSystemService(BluetoothManager::class.java)?.adapter ?: return emptyList()
            return adapter.bondedDevices.orEmpty().map { (it.name ?: it.address) to it.address }.sortedBy { it.first }
        }

        /**
         * Blocking. Tries a secure socket, then an insecure one, then (if the user
         * gave one) the bridge's RFCOMM channel directly. [onSocket] gets each
         * socket before connect() so the caller can close it to cancel.
         */
        fun open(context: Context, address: String, channel: Int?, onSocket: (Closeable) -> Unit): BluetoothLink {
            if (!hasBluetoothPermission(context)) throw NoPermission()
            val adapter = context.getSystemService(BluetoothManager::class.java)?.adapter
                ?: throw IOException("This phone has no Bluetooth.")
            if (!adapter.isEnabled) throw IOException("Bluetooth is off.")
            val pc = adapter.bondedDevices.orEmpty().firstOrNull { it.address == address }
                ?: throw IOException("The PC isn't paired any more. Choose it again in Settings.")
            try {
                adapter.cancelDiscovery()
            } catch (_: SecurityException) {
                // needs BLUETOOTH_SCAN on 31+; discovery isn't running anyway
            }
            val attempts = buildList<() -> BluetoothSocket> {
                add { pc.createRfcommSocketToServiceRecord(KAGI_UUID) }
                add { pc.createInsecureRfcommSocketToServiceRecord(KAGI_UUID) }
                if (channel != null) add {
                    pc.javaClass.getMethod("createRfcommSocket", Int::class.javaPrimitiveType)
                        .invoke(pc, channel) as BluetoothSocket
                }
            }
            var last: Exception? = null
            for (make in attempts) {
                var socket: BluetoothSocket? = null
                try {
                    socket = make()
                    onSocket(socket)
                    socket.connect()
                    return BluetoothLink(socket, pc.name ?: pc.address)
                } catch (e: Exception) {
                    last = e
                    try {
                        socket?.close()
                    } catch (_: IOException) {
                    }
                }
            }
            throw IOException("Couldn't connect to ${pc.name ?: "the PC"}.", last)
        }
    }
}
