1..6 | ForEach-Object {
    & "C:\Program Files\WireGuard\wireguard.exe" /uninstalltunnelservice vpn$_
}