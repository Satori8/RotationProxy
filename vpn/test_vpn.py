import time
import httpx


def check_tunnel_ip(tunnel_index):
    # Каждому из 6 туннелей соответствует свой локальный IP-адрес на ПК
    local_ip = f"10.8.0.1{tunnel_index}"

    try:
        # В актуальных версиях httpx привязка к IP настраивается через HTTPTransport
        transport = httpx.HTTPTransport(local_address=local_ip)
        
        # Создаем HTTP-клиент с использованием нашего настроенного транспорта
        with httpx.Client(transport=transport, timeout=5) as client:
            response = client.get("https://api.ipify.org")
            print(
                f"📡 Tunnel #{tunnel_index} ({local_ip}) -> Успешно! Ваш внешний IP: {response.text}"
            )
    except httpx.ConnectTimeout:
        print(
            f"❌ Tunnel #{tunnel_index} ({local_ip}) -> Ошибка: Таймаут соединения. Сервер Oracle не ответил."
        )
    except Exception as e:
        print(
            f"❌ Tunnel #{tunnel_index} ({local_ip}) -> Ошибка: {e}"
        )


if __name__ == "__main__":
    print("=" * 60)
    print("🔍 ТЕСТИРОВАНИЕ ВНЕШНИХ IP-АДРЕСОВ ДЛЯ ВСЕХ 6 АКТИВНЫХ СЛУЖБ")
    print("=" * 60)
    print("Начинаем параллельный опрос каналов...\n")

    start_time = time.time()

    # Опрашиваем все 6 туннелей по очереди
    for i in range(1, 7):
        check_tunnel_ip(i)

    end_time = time.time()
    print("-" * 60)
    print(f"Проверка завершена за {end_time - start_time:.2f} сек.")
    print("=" * 60)
    input("\nНажмите Enter для выхода...")