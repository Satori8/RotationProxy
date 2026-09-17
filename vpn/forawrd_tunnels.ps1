# 0. VPS Routing Loop Protection (ensures WireGuard UDP packets always route out physical interface)
$physical_route = Get-NetRoute -DestinationPrefix "0.0.0.0/0" | Where-Object { 
    $_.NextHop -ne "0.0.0.0" -and $_.NextHop -ne "10.8.0.1" -and 
    $_.InterfaceAlias -notlike "*WireGuard*" -and $_.InterfaceAlias -notlike "vpn*" 
} | Select-Object -First 1

if ($physical_route) {
    $gw = $physical_route.NextHop
    $pIfIndex = $physical_route.InterfaceIndex
    route ADD 158.178.159.108 MASK 255.255.255.255 $gw METRIC 1 IF $pIfIndex >$null 2>&1
    Write-Host "[ROUTING] Protected VPS endpoint 158.178.159.108 via physical gateway $gw (IF $pIfIndex)" -ForegroundColor Cyan
}

# 1. Look up all active adapters with IP addresses matching 10.8.0.X
$ip_addresses = Get-NetIPAddress -IPAddress "10.8.0.*" -AddressFamily IPv4

if (-not $ip_addresses) {
    Write-Host "[-] ERROR: No active WireGuard interfaces found with IP address in 10.8.0.X range!"
    Write-Host "Please ensure that your WireGuard services are fully started."
    return
}

Write-Host "============================================================"
Write-Host ">>> CONFIGURING FORWARD ROUTES FOR WIREGUARD INTERFACES"
Write-Host "============================================================"

foreach ($ip in $ip_addresses) {
    $ifIndex = $ip.InterfaceIndex
    $ifAlias = $ip.InterfaceAlias
    
    Write-Host "[+] Interface: $ifAlias (Index: $ifIndex, IP: $($ip.IPAddress))"
    
    # Check if there is already a default gateway (0.0.0.0/0) route for this interface
    $route = Get-NetRoute -InterfaceIndex $ifIndex -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue
    
    if (-not $route) {
        Write-Host "   -> Adding default gateway 10.8.0.1 for this interface..."
        # Add default route with metric 50
        New-NetRoute -InterfaceIndex $ifIndex -DestinationPrefix "0.0.0.0/0" -NextHop "10.8.0.1" -RouteMetric 50 -ErrorAction SilentlyContinue
    } else {
        Write-Host "   -> Default gateway route already exists (NextHop: $($route.NextHop), Metric: $($route.RouteMetric))."
    }
}
Write-Host "------------------------------------------------------------"
Write-Host "[+] Forward routing configuration completed."
