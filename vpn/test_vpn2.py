import socket
import time

# Локальный IP вашего Oracle сервера внутри сети Wireguard
TARGET_IP = "10.8.0.1"
PORT = 8080
LOCAL_IPS = ["10.8.0.11", "10.8.0.12", "10.8.0.13", "10.8.0.14", "10.8.0.15", "10.8.0.16"]

print("============================================================")
print("🔍 ТЕСТИРОВАНИЕ ЛОКАЛЬНЫХ КАНАЛОВ WIREGUARD ДО LLAMA-SERVER")
print("============================================================")

for idx, local_ip in enumerate(LOCAL_IPS, 1):
    try:
        # Создаем TCP-сокет
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3.0)
        
        # Жестко привязываем сокет к локальному IP конкретного туннеля
        s.bind((local_ip, 0))
        
        # Стучимся на внутренний порт модели на Oracle
        s.connect((TARGET_IP, PORT))
        
        # Отправляем быстрый HTTP-запрос
        s.sendall(b"GET /v1/models HTTP/1.1\r\nHost: 10.8.0.1:8080\r\nConnection: close\r\n\r\n")
        response = s.recv(1024)
        s.close()
        
        if b"200 OK" in response or b"object" in response:
            print(f"📡 Tunnel #{idx} ({local_ip}) -> УСПЕШНО! Модель ответила за доли секунды.")
        else:
            print(f"⚠️ Tunnel #{idx} ({local_ip}) -> Подключено, но странный ответ: {response[:50]}")
            
    except Exception as e:
        print(f"❌ Tunnel #{idx} ({local_ip}) -> ОШИБКА СВЯЗИ: {e}")

print("------------------------------------------------------------")
print("Проверка завершена.")