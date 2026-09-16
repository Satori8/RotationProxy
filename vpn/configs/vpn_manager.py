import ctypes
import os
import subprocess
import sys
import time


class WindowsWireGuardManager:
    """Универсальный класс-библиотека для управления туннелями WireGuard и системными маршрутами на Windows."""

    def __init__(self, configs_dir=None):
        self.vps_ip = "158.178.159.108"  # Публичный IP вашего сервера Oracle
        self.wg_gateway = "10.8.0.1"     # Внутренний IP-шлюз WireGuard на сервере
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
        result = subprocess.run(
            ["powershell", "-Command", cmd], capture_output=True, text=True
        )
        return result.stdout.strip(), result.stderr.strip()

    def is_any_tunnel_active(self) -> bool:
        """Возвращает True, если хотя бы одна служба vpn1-vpn6 запущена (Running) в системе"""
        output, _ = self.run_ps_cmd('Get-Service -Name "WireGuardTunnel$*" | Where-Object {$_.Status -eq "Running"}')
        return len(output) > 0

    def uninstall_all_services(self):
        """Полностью останавливает и удаляет из Windows все 6 служб туннелей"""
        self.elevate()
        print("🧹 Удаление служб WireGuard из системы...")
        self.disable_system_routing() # На всякий случай очищаем маршруты перед удалением
        for name in self.tunnel_names:
            subprocess.run(
                [self.wg_path, "/uninstalltunnelservice", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        time.sleep(1.5)
        print("✅ Все службы Wireguard успешно удалены.")

    def install_and_start_all_services(self):
        """Регистрирует, запускает все 6 туннелей и настраивает шлюзы с метрикой 500"""
        self.elevate()
        self.uninstall_all_services()

        print("\n⚙️ Регистрация и запуск 6 туннелей в системе параллельно...")
        for i, name in enumerate(self.tunnel_names, 1):
            conf_path = os.path.join(self.configs_dir, f"{name}.conf")

            if os.path.exists(conf_path):
                result = subprocess.run(
                    [self.wg_path, "/installtunnelservice", conf_path],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    print(f"  -> {name} успешно запущен (локальный IP: 10.8.0.1{i})")
                    # Прописываем шлюз по умолчанию с метрикой 500 (низкий приоритет) для обхода WinError 10051
                    ps_cmd = f'New-NetRoute -DestinationPrefix "0.0.0.0/0" -NextHop "{self.wg_gateway}" -InterfaceAlias "{name}" -RouteMetric 500 -Confirm:$false -ErrorAction SilentlyContinue'
                    subprocess.run(["powershell", "-Command", ps_cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    print(f"  -> ❌ Ошибка при запуске {name}: {result.stderr.strip()}")
            else:
                print(f"  -> ❌ Файл не найден: {conf_path}")
        print("\n🎉 Все доступные туннели запущены и настроены!")

    def get_home_gateway_and_interface(self):
        """Автоматически находит имя физической карты и адрес домашнего роутера"""
        cmd = 'Get-NetRoute -DestinationPrefix "0.0.0.0/0" | Where-Object {$_.NextHop -ne "0.0.0.0" -and $_.InterfaceAlias -notlike "*WireGuard*"} | Select-Object -First 1 | ForEach-Object { "$($_.NextHop)|$($_.InterfaceAlias)" }'
        output, _ = self.run_ps_cmd(cmd)
        if "|" in output:
            gw, if_alias = output.split("|")
            return gw.strip(), if_alias.strip()
        return None, None

    def disable_system_routing(self):
        """Очищает кастомные маршруты и возвращает интернет к домашнему провайдеру"""
        self.elevate()
        print("🧹 Очистка системных VPN-маршрутов в Windows...")
        self.run_ps_cmd(f'Remove-NetRoute -DestinationPrefix "{self.vps_ip}/32" -Confirm:$false -ErrorAction SilentlyContinue')
        for tunnel in self.tunnel_names:
            self.run_ps_cmd(f'Remove-NetRoute -DestinationPrefix "0.0.0.0/0" -NextHop "{self.wg_gateway}" -InterfaceAlias "{tunnel}" -Confirm:$false -ErrorAction SilentlyContinue')
        print("✅ Системные маршруты очищены.")

    def enable_system_routing_via(self, ip_index):
        """Направляет весь трафик ПК через выбранный туннель (1-6) без перезапуска служб"""
        self.elevate()
        if ip_index < 1 or ip_index > len(self.tunnel_names):
            print("❌ ОШИБКА: Неверный индекс. Допустимый диапазон: 1-6")
            return

        self.disable_system_routing()
        target_tunnel = self.tunnel_names[ip_index - 1]

        gw, physical_if = self.get_home_gateway_and_interface()
        if not gw or not physical_if:
            print("❌ ОШИБКА: Не удалось определить домашний шлюз роутера.")
            return

        print(f"🔌 Направление системного трафика через {target_tunnel}...")
        # Защита от петли маршрутизации
        cmd_loop_protection = f'New-NetRoute -DestinationPrefix "{self.vps_ip}/32" -NextHop "{gw}" -InterfaceAlias "{physical_if}" -RouteMetric 1 -Confirm:$false'
        self.run_ps_cmd(cmd_loop_protection)

        # Добавляем шлюз по умолчанию через выбранный туннель с высоким приоритетом (метрика 5)
        cmd_default_route = f'New-NetRoute -DestinationPrefix "0.0.0.0/0" -NextHop "{self.wg_gateway}" -InterfaceAlias "{target_tunnel}" -RouteMetric 5 -Confirm:$false'
        _, err_route = self.run_ps_cmd(cmd_default_route)

        if not err_route:
            print(f"✅ УСПЕХ: Весь трафик теперь идет через {target_tunnel}!")
        else:
            print(f"❌ Ошибка изменения маршрутов: {err_route}")


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
        print(f"Активность туннелей в системе: {'🟢 РАБОТАЮТ' if active else '🔴 ОТКЛЮЧЕНЫ'}")
    elif user_input:
        try:
            index = int(user_input)
            manager.enable_system_routing_via(index)
        except ValueError:
            print("❌ ОШИБКА: Неверный ввод.")
    input("\nНажмите Enter для выхода...")


if __name__ == "__main__":
    main()