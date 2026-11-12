# -*- coding: utf-8 -*-
"""Мини-HTTP/SOCKS-совместимый прокси для SSH-туннеля «домашний ПК -> VPS».

Запускается НА ДОМАШНЕЙ машине в Норильске. Финский VPS через `ssh -R`
получает локальный порт, и бот (RU_PROXY=http://127.0.0.1:12080) ходит
на гео-блокированные российские сайты с вашего домашнего российского IP.

Поддерживает:
  - CONNECT host:port (для https-целей, как это делает httpx);
  - обычные HTTP-запросы в absolute-URI форме (переписывает в origin-form).

Безопасность: по умолчанию пропускает ТОЛЬКО домены из белого списка
(норильск.рф, norilsk-city.ru), чтобы туннель нельзя было использовать
как открытый прокси для всего интернета.

Запуск (дома):
    .venv\\Scripts\\python.exe tunnel\\rus_proxy.py --port 8888

Зависимостей нет — только стандартная библиотека.
"""
from __future__ import annotations

import argparse
import re
import socket
import socketserver
import sys
import threading
import time

# Домены, к которым прокси разрешает ходить (суффиксное совпадение)
DEFAULT_ALLOW = (
    "xn--h1aecgfmj1g.xn--p1ai",  # норильск.рф
    "www.xn--h1aecgfmj1g.xn--p1ai",
    "norilsk-city.ru",
    "www.norilsk-city.ru",
)

ALLOW = set(DEFAULT_ALLOW)

LOG_LOCK = threading.Lock()


def log(msg: str) -> None:
    with LOG_LOCK:
        print(msg, flush=True)


def allowed(host: str) -> bool:
    host = (host or "").lower().strip().rstrip(".")
    if ":" in host:  # отрезаем порт из "host:port"
        host = host.split(":", 1)[0]
    return any(host == d or host.endswith("." + d) for d in ALLOW)


def dns_resolve(host: str, port: int) -> tuple[socket.socket | None, str]:
    """Резолвит и подключается ЛОКАЛЬНО (с российского IP домашней машины)."""
    last: OSError | None = None
    for attempt in (1, 2):  # DNS за VPN бывает капризным — одна повторная попытка
        try:
            info = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except OSError as e:
            last = e
        else:
            for _fam, _typ, _proto, _cname, addr in info:
                try:
                    return socket.create_connection(addr, timeout=15), ""
                except OSError as e:
                    last = e
        if attempt == 1:
            time.sleep(0.5)
    return None, f"DNS/connect: {last}"


def relay(a: socket.socket, b: socket.socket) -> None:
    try:
        while True:
            data = a.recv(65536)
            if not data:
                break
            b.sendall(data)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def connect_relay(client: socket.socket, hostport: str) -> None:
    host, _, port = hostport.partition(":")
    port = int(port or 443)
    if not allowed(host):
        client.sendall(b"HTTP/1.1 403 Forbidden\r\nProxy: domain not allowed\r\n\r\n")
        log(f"DENY  {host}:{port}")
        return
    target, err = dns_resolve(host, port)
    if target is None:
        client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        log(f"FAIL  {host}:{port} -> {err}")
        return
    try:
        client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        t1 = threading.Thread(target=relay, args=(client, target), daemon=True)
        t2 = threading.Thread(target=relay, args=(target, client), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        log(f"OK    {host}:{port}")
    finally:
        target.close()


def forward_http_with(client: socket.socket, line: str, rest: bytes) -> None:
    """HTTP-запрос: первая строка уже прочитана, `rest` — недочитанные байты."""
    parts = line.split()
    if len(parts) < 2 or not parts[1].startswith("http://"):
        client.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        return
    method, url = parts[0], parts[1]
    headers = [rest]
    if not (b"\r\n\r\n" in rest or b"\n\n" in rest):
        while True:  # запрос пришёл кусками — дочитываем заголовки
            chunk = client.recv(65536)
            if not chunk:
                break
            headers.append(chunk)
            if b"\r\n\r\n" in chunk or b"\n\n" in chunk:
                break
    scheme, _, rest_url = url.partition("://")
    netloc, _, path = rest_url.partition("/")
    host = netloc.split(":", 1)[0]
    port = int(netloc.split(":", 1)[1]) if ":" in netloc else 80
    if not allowed(host):
        client.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
        log(f"DENY  {host}")
        return
    target, err = dns_resolve(host, port)
    if target is None:
        client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        log(f"FAIL  {host}:{port} -> {err}")
        return
    try:
        raw = b"".join(headers)
        # свой Connection: close — дубликат из исходного запроса убираем
        raw = re.sub(rb"(?i)^connection:[^\r\n]*\r?\n", b"", raw, flags=re.MULTILINE)
        out = f"{method} /{path} HTTP/1.1\r\nConnection: close\r\n".encode() + raw
        target.sendall(out)
        relay(target, client)
        log(f"OK    {method} {host}")
    finally:
        target.close()


class Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        client = self.request
        try:
            client.settimeout(60)
            first = b""
            while b"\r\n" not in first and b"\n" not in first and len(first) < 8192:
                chunk = client.recv(8192)
                if not chunk:
                    return
                first += chunk
            line = first.split(b"\n", 1)[0].decode("latin-1", errors="replace").strip()
            if line.upper().startswith("CONNECT "):
                connect_relay(client, line.split()[1])
            else:
                rest = first.split(b"\n", 1)[1] if b"\n" in first else b""
                forward_http_with(client, line, rest)
        except OSError:
            pass


class ThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    global ALLOW
    parser = argparse.ArgumentParser(description="Мини-прокси для SSH-туннеля бота")
    parser.add_argument("--port", type=int, default=8888)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument(
        "--allow",
        default="",
        help="доп. домены через запятую (к базовому белому списку)",
    )
    args = parser.parse_args()
    if args.allow:
        ALLOW = ALLOW | {d.strip().lower() for d in args.allow.split(",") if d.strip()}

    server = ThreadingServer((args.bind, args.port), Handler)
    log(f"rus_proxy слушает {args.bind}:{args.port}; белый список: {sorted(ALLOW)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    main()
