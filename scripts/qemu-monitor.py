#!/usr/bin/env python3
import argparse
import socket
import time


parser = argparse.ArgumentParser()
parser.add_argument("command")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=55557)
args = parser.parse_args()

with socket.create_connection((args.host, args.port), timeout=10) as sock:
    sock.settimeout(1)
    time.sleep(0.15)
    try:
        while sock.recv(65536):
            pass
    except (TimeoutError, socket.timeout):
        pass
    sock.sendall((args.command + "\n").encode("ascii"))
    time.sleep(0.5)
    chunks = []
    try:
        while True:
            chunks.append(sock.recv(65536))
    except (TimeoutError, socket.timeout):
        pass
print(b"".join(chunks).decode("utf-8", errors="replace"), end="")
