import ctypes
import os
import subprocess
import sys
import time


class LocalWireGuardManager:
    """Класс-библиотека для управления локальными туннелями WireGuard на Windows."""

    def __init__(self, configs_dir=None):
        # Путь к официальной утилите WireGuard на Windows
        self.wg_path = r"C:\Program Files\WireGuard\wireguard.exe"
        
        # По умолчанию ищем конфиги в подпапке "configs" рядом со скриптом
        if configs_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self.configs_dir = os.path.join(base_dir, "configs")
        else:
            self.configs_dir = configs_dir

        # Имена ваших 6 файлов конфигураций
        self.tunnel_names = ["vpn1", "vpn2", "vpn3", "vpn4", "vpn5", "vpn6"]

    def check_environment(self):
        """Проверяет наличие исполняемого файла WireGuard и права Администратора."""
        if not os.path.exists(self.wg_path):
            print(f"❌ ОШИБКА: Не найден WireGuard по пути: {self.wg_path}")
            print("Установите официальный клиент WireGuard для Windows.")
            return False

        try:
            if not ctypes.windll.shell32.IsUserAnAdmin():
                print("❌ ОШИБКА: Скрипт запущен без прав Администратора.")
                return False
        except Exception:
            return False
        return True

    def disconnect_all(self):
        """Полностью останавливает и удаляет из Windows все наши туннели."""
        if not self.check_environment():
            return False

        print("🔌 Отключение всех активных туннелей WireGuard...")
        for name in self.tunnel_names:
            subprocess.run(
                [self.wg_path, "/uninstalltunnelservice", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        time.sleep(1.5)  # Пауза для удаления интерфейсов ОС Windows
        print("✅ Все локальные туннели успешно отключены.")
        return True

    def switch_to_ip(self, ip_index):
        """Отключает старый туннель и динамически запускает vpnX.conf из папки configs."""
        if not self.check_environment():
            return False

        if ip_index < 1 or ip_index > len(self.tunnel_names):
            print(f"❌ ОШИБКА: Неверный индекс (должен быть от 1 до 6)")
            return False

        # 1. Сначала принудительно очищаем систему от старых туннелей
        self.disconnect_all()

        # 2. Определяем путь к нужному файлу vpnX.conf
        target_name = self.tunnel_names[ip_index - 1]
        conf_file_path = os.path.join(self.configs_dir, f"{target_name}.conf")

        if not os.path.exists(conf_file_path):
            print(f"❌ ОШИБКА: Файл конфигурации не найден по пути: {conf_file_path}")
            return False

        print(f"🔌 Динамическая регистрация и запуск туннеля {target_name}...")
        
        # Команда /installtunnelservice регистрирует службу Windows напрямую из файла и запускает её
        result = subprocess.run(
            [self.wg_path, "/installtunnelservice", conf_file_path],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            print(f"✅ УСПЕХ: Подключено к {target_name}! Внешний IP сменен на №{ip_index}.")
            return True
        else:
            print(f"❌ Ошибка WireGuard при создании службы: {result.stderr.strip()}")
            return False


def is_admin():
    """Проверяет, запущен ли скрипт с правами администратора Windows."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def main():
    # --- БЛОК АВТОМАТИЧЕСКОГО ЗАПРОСА ПРАВ АДМИНИСТРАТОРА ---
    # Если скрипт запускается как самостоятельное приложение, он сам запросит права у Windows
    if not is_admin():
        print("🔑 Запрос прав Администратора Windows...")
        try:
            # Перезапускаем этот же скрипт с правами администратора
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        except Exception as e:
            print(f"❌ Не удалось получить права Администратора: {e}")
        sys.exit()

    manager = LocalWireGuardManager()

    # --- РЕЖИМ 1: Работа через аргументы командной строки (CLI) ---
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip().lower()
        
        if arg in ["stop", "off", "disable", "0"]:
            manager.disconnect_all()
        else:
            try:
                index = int(arg)
                manager.switch_to_ip(index)
            except ValueError:
                print("❌ ОШИБКА: Аргумент должен быть числом от 1 до 6 или командой 'stop'.")
        
        # Короткая пауза, чтобы пользователь успел прочитать вывод перед закрытием консоли
        time.sleep(2)

    # --- РЕЖИМ 2: Интерактивный режим (без аргументов CLI) ---
    else:
        print("="*60)
        print("🎛️  ПАНЕЛЬ УПРАВЛЕНИЯ ТУННЕЛЯМИ WIREGUARD")
        print("="*60)
        print("Введите номер от 1 до 6, чтобы включить нужный туннель.")
        print("Введите '0' или 'stop', чтобы полностью отключить VPN.")
        print("Нажмите Enter для выхода без изменений.")
        print("-"*60)

        try:
            user_input = input("👉 Введите команду: ").strip().lower()
            
            if not user_input:
                print("Выход без изменений.")
                sys.exit()
            
            if user_input in ["stop", "off", "disable", "0"]:
                manager.disconnect_all()
            else:
                index = int(user_input)
                manager.switch_to_ip(index)
        except ValueError:
            print("❌ ОШИБКА: Ввод должен быть числом от 1 до 6.")
        except KeyboardInterrupt:
            print("\nОтменено пользователем.")
        
        # Держим консоль открытой, чтобы увидеть результат перед выходом при запуске дабл-кликом
        print("\nНажмите Enter для выхода...")
        input()


# Точка входа: если файл импортируется как библиотека, интерактивный интерфейс не запускается
if __name__ == "__main__":
    main()