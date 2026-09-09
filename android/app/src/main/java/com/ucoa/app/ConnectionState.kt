package com.ucoa.app

object ConnectionState {
    fun current(): ConnectionStatus = when {
        PermissionCoordinator.isServiceLive() -> ConnectionStatus.CONNECTED
        else -> ConnectionStatus.DISCONNECTED
    }
}
