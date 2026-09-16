# 2. Переходим в вашу папку с конфигурациями
cd "d:\Work\Active\server-services\vpn_switcher\configs\"

# 3. Регистрируем службы заново, принудительно получая ПОЛНЫЙ путь к файлам
1..6 | ForEach-Object {
    $conf = ".\vpn$_.conf"
    if (Test-Path $conf) {
        # Получаем полный путь (например, d:\Work\Active\server-services\vpn_switcher\configs\vpn1.conf)
        $absolutePath = (Resolve-Path $conf).Path
        Write-Host "Регистрация туннеля по абсолютному пути: $absolutePath"
        
        # Передаем утилите строго полный путь
        & "C:\Program Files\WireGuard\wireguard.exe" /installtunnelservice $absolutePath
    } else {
        Write-Host "❌ Ошибка: Файл не найден в текущей папке: $conf" -ForegroundColor Red
    }
}