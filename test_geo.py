# -*- coding: utf-8 -*-
"""Диагностика доступности норильск.рф с текущего IP.

Запустите дважды — с включённым и с выключенным VPN — и сравните вывод:

    .venv\\Scripts\\python.exe test_geo.py

Если без VPN DNS начинает отвечать (NOERROR + IP) и страница открывается,
значит сайт фильтрует зарубежный трафик, и боту нужен российский IP
(локально — запуск без VPN, на VPS — хостинг в России или RU_PROXY).
"""
import http.client
import socket
import ssl
import struct

HOST_PUNY = "xn--h1aecgfmj1g.xn--p1ai"
NS_SERVERS = ["89.104.95.30", "89.104.93.35", "91.217.20.20", "193.232.146.1"]


def my_ip() -> str:
    try:
        with socket.create_connection(("1.1.1.1", 80), timeout=5) as s:
            return s.getsockname()[0]
    except OSError:
        return "?"


def dns_to_resolver(server: str, name: str) -> None:
    tid = struct.pack(">H", 1234)
    q = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
    packet = tid + struct.pack(">HHHHH", 0x0100, 1, 0, 0, 0) + q + struct.pack(">HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(5)
    try:
        s.sendto(packet, (server, 53))
        data, _ = s.recvfrom(4096)
        rcode = data[3] & 0x0F
        ancount = struct.unpack(">H", data[6:8])[0]
        names = {0: "NOERROR (отвечает!)", 2: "SERVFAIL", 3: "NXDOMAIN", 5: "REFUSED"}
        ips = []
        if ancount:
            idx = data.find(b"\xc0\x0c\x00\x01\x00\x01")
            while idx != -1 and len(ips) < 3:
                start = idx + 12
                if struct.unpack(">H", data[idx + 10:idx + 12])[0] == 4:
                    ips.append(".".join(map(str, data[start:start + 4])))
                idx = data.find(b"\xc0\x0c\x00\x01\x00\x01", idx + 1)
        print(f"    {server}: {names.get(rcode, 'rcode ' + str(rcode))}  IP={ips or '-'}")
    except socket.timeout:
        print(f"    {server}: таймаут (нет ответа за 5 c)")
    except OSError as e:
        print(f"    {server}: ошибка {e!r}")
    finally:
        s.close()


def http_probe(ip: str) -> None:
    unverified = ssl._create_unverified_context()  # noqa: SLF001 — диагностика
    for scheme, kind in (("http", "HTTPConnection"), ("https", "HTTPSConnection")):
        try:
            if scheme == "https":
                conn = http.client.HTTPSConnection(ip, 443, timeout=10, context=unverified)
            else:
                conn = http.client.HTTPConnection(ip, 80, timeout=10)
            conn.request("GET", "/weather/",
                         headers={"Host": HOST_PUNY, "User-Agent": "Mozilla/5.0"})
            resp = conn.getresponse()
            body = resp.read(200)
            print(f"    {scheme}://{ip} -> HTTP {resp.status}, {len(body)} байт")
            conn.close()
            return
        except OSError as e:
            print(f"    {scheme}://{ip} -> {type(e).__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"    {scheme}://{ip} -> {type(e).__name__}: {e}")


print(f"Мой локальный IP (как сайт его видит): {my_ip()}")
print("\n1) Спросим авторитативные NS-серверы домена напрямую:")
for ns in NS_SERVERS:
    dns_to_resolver(ns, HOST_PUNY)

print("\n2) Разрешение через локальный DNS вашего провайдера:")
import subprocess  # noqa: E402
try:
    out = subprocess.run(["nslookup", HOST_PUNY], capture_output=True, text=True,
                         timeout=15, encoding="cp1251", errors="replace")
    tail = [ln for ln in out.stdout.splitlines() if ln.strip()][-3:]
    for ln in tail:
        print("   ", ln)
except Exception as e:  # noqa: BLE001
    print("    nslookup недоступен:", e)

print("\n3) Попытка открыть страницу по прямому IP (обход DNS):")
ip = "195.24.67.178"  # известный адрес сервера норильск.рф
http_probe(ip)

print("\nВывод: если с VPN выключенным пункты 1-3 показывают IP и HTTP 200 —")
print("сайт работает только из России, боту нужен российский IP/RU_PROXY.")
