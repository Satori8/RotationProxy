import ctypes
import os
import subprocess
import sys
import time


class WindowsWireGuardManager:
    """Универсальный класс-библиотека для управления туннелями WireGuard и системными маршрутами на Windows."""

    def __init__(self, configs_dir=None):
        self.vps_ip = "158.178.159.108"  # Публичный IP вашего сервера Oracle
        self.wg_gateway = "10.8.0.1"  # Внутренний IP-шлюз WireGuard на сервере
        self.wg_path = r"C:\Program Files\WireGuard\wireguard.exe"

        # По умолчанию ищем конфиги в подпапке "configs" рядом со скриптом
        if configs_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self.configs_dir = os.path.join(base_dir, "configs")
        else:
            self.configs_dir = configs_dir

        self.tunnel_names = ["vpn1", "vpn2", "vpn3", "vpn4", "vpn5", "vpn6"]

    def is_admin(self):
        """Проверяет права Администратора в Windows"""
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except Exception:
            return False

    def elevate(self):
        """Запрашивает права Администратора у Windows (UAC-окно)"""
        if not self.is_admin():
            print("🔑 Запрос прав Администратора Windows...")
            try:
                ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", sys.executable, " ".join(sys.argv), None, 1
                )
            except Exception as e:
                print(f"❌ Не удалось получить права Администратора: {e}")
            sys.exit()

    def run_ps_cmd(self, cmd):
        """Выполняет команду в PowerShell и возвращает вывод"""
        try:
            result = subprocess.run(
                ["powershell", "-Command", cmd],
                capture_output=True,
                text=True,
                errors="replace",
            )
            stdout = result.stdout.strip() if result.stdout else ""
            stderr = result.stderr.strip() if result.stderr else ""
            return stdout, stderr
        except Exception as e:
            return "", str(e)

    def is_any_tunnel_active(self) -> bool:
        """Возвращает True, если хотя бы одна служба vpn1-vpn6 запущена (Running) в системе"""
        output, _ = self.run_ps_cmd(
            'Get-Service -Name "WireGuardTunnel$*" | Where-Object {$_.Status -eq "Running"}'
        )
        return len(output) > 0

    def uninstall_all_services(self, print_cb=None):
        """Fully stop and remove all 6 WireGuard tunnel services from Windows."""
        self.elevate()

        def log_msg(msg):
            if print_cb:
                print_cb(msg)
            else:
                print(msg)

        log_msg("🧹 Removing WireGuard tunnel services from Windows system...")
        self.disable_system_routing()  # Clean up system routing routes before uninstalling
        for name in self.tunnel_names:
            subprocess.run(
                [self.wg_path, "/uninstalltunnelservice", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        # Wait up to 10s until all WireGuard services are completely removed from SCM database to prevent "delete pending" race conditions
        start_wait = time.time()
        while time.time() - start_wait < 10.0:
            output, _ = self.run_ps_cmd(
                'Get-Service -Name "WireGuardTunnel$*" -ErrorAction SilentlyContinue'
            )
            if not output or "WireGuardTunnel" not in output:
                break
            time.sleep(0.5)
        time.sleep(1.0)  # Extra safety margin
        log_msg("✅ All WireGuard services successfully uninstalled.")

    def install_and_start_all_services(self, print_cb=None):
        """Register, launch all 6 tunnels, and configure baseline metrics."""
        self.elevate()

        def log_msg(msg):
            if print_cb:
                print_cb(msg)
            else:
                print(msg)

        self.uninstall_all_services(print_cb=print_cb)

        log_msg("⚙️ Registering and launching 6 VPN tunnels in parallel...")
        for i, name in enumerate(self.tunnel_names, 1):
            conf_path = os.path.join(self.configs_dir, f"{name}.conf")

            if os.path.exists(conf_path):
                result = subprocess.run(
                    [self.wg_path, "/installtunnelservice", conf_path],
                    capture_output=True,
                    text=True,
                    errors="replace",
                )
                if result.returncode == 0:
                    log_msg(f"  -> {name} started successfully (local IP: 10.8.0.1{i})")
                    # Set up default route with metric 500 (low priority) to avoid WinError 10051
                    ps_cmd = f'New-NetRoute -DestinationPrefix "0.0.0.0/0" -NextHop "{self.wg_gateway}" -InterfaceAlias "{name}" -RouteMetric 500 -Confirm:$false -ErrorAction SilentlyContinue'
                    subprocess.run(
                        ["powershell", "-Command", ps_cmd],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    err_msg = result.stderr.strip() if result.stderr else ""
                    log_msg(f"  -> ❌ Error launching {name}: {err_msg}")
            else:
                log_msg(f"  -> ❌ Configuration file not found: {conf_path}")
        log_msg("🎉 All available tunnels registered and configured!")

    def get_home_gateway_and_interface(self):
        """Automatically resolve the physical interface name, home gateway IP, and interface index."""
        cmd = 'Get-NetRoute -DestinationPrefix "0.0.0.0/0" | Where-Object {$_.NextHop -ne "0.0.0.0" -and $_.InterfaceAlias -notlike "*WireGuard*" -and $_.InterfaceAlias -notlike "vpn*"} | Select-Object -First 1 | ForEach-Object { "$($_.NextHop)|$($_.InterfaceAlias)|$($_.InterfaceIndex)" }'
        output, _ = self.run_ps_cmd(cmd)
        if "|" in output:
            parts = output.split("|")
            if len(parts) == 3:
                return parts[0].strip(), parts[1].strip(), parts[2].strip()
        return None, None, None

    def disable_system_routing(self, print_cb=None):
        """Clear custom default routes and restore standard internet connection."""
        self.elevate()

        def log_msg(msg):
            if print_cb:
                print_cb(msg)
            else:
                print(msg)

        log_msg("🧹 Clearing system VPN routing tables in Windows...")
        # Delete the VPS bypass route using route.exe to avoid Ndu.sys BSOD
        subprocess.run(
            ["route", "DELETE", self.vps_ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Delete the /1 split default routes using route.exe to avoid Ndu.sys BSOD
        subprocess.run(
            ["route", "DELETE", "0.0.0.0", "MASK", "128.0.0.0"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["route", "DELETE", "128.0.0.0", "MASK", "128.0.0.0"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        log_msg("✅ System default routes cleared.")

    def enable_system_routing_via(self, ip_index, print_cb=None):
        """Route all PC traffic through the chosen tunnel interface (1-6) on the fly."""
        self.elevate()

        def log_msg(msg):
            if print_cb:
                print_cb(msg)
            else:
                print(msg)

        if ip_index < 1 or ip_index > len(self.tunnel_names):
            log_msg("❌ ERROR: Invalid tunnel index. Allowed range is 1-6.")
            return

        self.disable_system_routing(print_cb=print_cb)
        target_tunnel = self.tunnel_names[ip_index - 1]

        # Resolve the target tunnel interface index via PowerShell (safe — only reading, no routing changes)
        stdout, _ = self.run_ps_cmd(
            f'Get-NetIPInterface -InterfaceAlias "{target_tunnel}" -AddressFamily IPv4 | Select-Object -ExpandProperty InterfaceIndex'
        )
        if_index = stdout.strip()
        if not if_index:
            log_msg(f"❌ ERROR: Unable to resolve interface index for {target_tunnel}")
            return

        gw, physical_if, physical_if_index = self.get_home_gateway_and_interface()
        if not gw or not physical_if or not physical_if_index:
            log_msg("❌ ERROR: Unable to auto-resolve home gateway route interface.")
            return

        log_msg(f"🔌 Routing all system traffic through {target_tunnel}...")

        # Routing loop protection: keep Oracle VPS traffic bound directly via home interface using route.exe to avoid Ndu.sys BSOD
        cmd_vps = [
            "route",
            "ADD",
            self.vps_ip,
            "MASK",
            "255.255.255.255",
            gw,
            "METRIC",
            "1",
            "IF",
            physical_if_index,
        ]
        subprocess.run(cmd_vps, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Add the split default /1 routes pointing to the target tunnel using route.exe to avoid Ndu.sys BSOD
        cmd1 = [
            "route",
            "ADD",
            "0.0.0.0",
            "MASK",
            "128.0.0.0",
            self.wg_gateway,
            "METRIC",
            "5",
            "IF",
            if_index,
        ]
        cmd2 = [
            "route",
            "ADD",
            "128.0.0.0",
            "MASK",
            "128.0.0.0",
            self.wg_gateway,
            "METRIC",
            "5",
            "IF",
            if_index,
        ]
        subprocess.run(cmd1, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(cmd2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        log_msg(f"✅ SUCCESS: All PC traffic is now routed through {target_tunnel}!")


def main():
    # Ручной интерактивный режим, если запустить файл напрямую
    manager = WindowsWireGuardManager()

    if not manager.is_admin():
        manager.elevate()

    print("=" * 60)
    print("🎛️  УПРАВЛЕНИЕ МУЛЬТИ-VPN ИНФРАСТРУКТУРОЙ")
    print("=" * 60)
    print("1. Введите 'start', чтобы запустить все 6 служб параллельно.")
    print("2. Введите число от 1 до 6, чтобы пустить ВЕСЬ трафик ПК через этот IP.")
    print("3. Введите 'stop', чтобы полностью отключить и удалить все службы.")
    print("4. Введите 'status', чтобы проверить активность туннелей.")
    print("5. Нажмите Enter для выхода.")
    print("-" * 60)

    user_input = input("👉 Введите команду: ").strip().lower()
    if user_input == "start":
        manager.install_and_start_all_services()
    elif user_input in ["stop", "delete"]:
        manager.uninstall_all_services()
    elif user_input == "status":
        active = manager.is_any_tunnel_active()
        print(
            f"Активность туннелей в системе: {'🟢 РАБОТАЮТ' if active else '🔴 ОТКЛЮЧЕНЫ'}"
        )
    elif user_input:
        try:
            index = int(user_input)
            manager.enable_system_routing_via(index)
        except ValueError:
            print("❌ ОШИБКА: Неверный ввод.")
    input("\nНажмите Enter для выхода...")


if __name__ == "__main__":
    main()
