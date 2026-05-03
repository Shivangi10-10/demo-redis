"""
mini_redis.py
A single-file, in-memory Redis-like server implemented from scratch using Python's
standard library (socket, threading, time). No external dependencies required.

Supported commands:
  PING, SET, GET, DEL, EXISTS, EXPIRE, TTL,
  LPUSH, RPUSH, LPOP, RPOP, LRANGE,
  HSET, HGET, HDEL, HGETALL,
  INCR, DECR, KEYS, FLUSHALL, QUIT
"""

import socket          # Low-level TCP networking
import threading       # One thread per client connection
import time            # Used for TTL / expiry tracking
import re              # Parsing RESP protocol messages


# ---------------------------------------------------------------------------
# 1.  DATA STORE
# ---------------------------------------------------------------------------

store: dict = {}        # Main key-value store  {key: value}
expiry: dict = {}       # TTL map               {key: unix_expiry_time}
store_lock = threading.Lock()   # Mutex so multiple threads don't corrupt data


# ---------------------------------------------------------------------------
# 2.  TTL HELPERS
# ---------------------------------------------------------------------------

def is_expired(key: str) -> bool:
    """Return True if the key has a TTL that has already passed."""
    if key in expiry:
        if time.time() > expiry[key]:   # Current time exceeded the deadline
            del store[key]              # Lazy-delete the value
            del expiry[key]             # Clean up the expiry record
            return True
    return False


def ttl_seconds(key: str) -> int:
    """Return remaining TTL in whole seconds, or -1 (no expiry), or -2 (gone)."""
    if key not in store or is_expired(key):
        return -2                               # Key does not exist
    if key not in expiry:
        return -1                               # Key exists but has no expiry
    remaining = expiry[key] - time.time()
    return max(0, int(remaining))


# ---------------------------------------------------------------------------
# 3.  RESP PROTOCOL  (Redis Serialisation Protocol)
# ---------------------------------------------------------------------------
# Redis clients communicate over a simple text protocol called RESP.
# Each message type starts with a prefix character:
#   +  Simple string      e.g.  +OK\r\n
#   -  Error              e.g.  -ERR message\r\n
#   :  Integer            e.g.  :42\r\n
#   $  Bulk string        e.g.  $5\r\nhello\r\n   ($-1\r\n = null)
#   *  Array              e.g.  *2\r\n$3\r\nGET\r\n$3\r\nfoo\r\n

def encode_simple(msg: str) -> bytes:
    return f"+{msg}\r\n".encode()

def encode_error(msg: str) -> bytes:
    return f"-ERR {msg}\r\n".encode()

def encode_integer(n: int) -> bytes:
    return f":{n}\r\n".encode()

def encode_bulk(value) -> bytes:
    """Encode a Python string (or None) as a RESP bulk string."""
    if value is None:
        return b"$-1\r\n"                        # Null bulk string
    s = str(value)
    return f"${len(s)}\r\n{s}\r\n".encode()

def encode_array(items: list) -> bytes:
    """Encode a Python list as a RESP array of bulk strings."""
    if items is None:
        return b"*-1\r\n"
    parts = [f"*{len(items)}\r\n".encode()]
    for item in items:
        parts.append(encode_bulk(item))
    return b"".join(parts)


def parse_resp(data: str) -> list[list[str]]:
    """
    Parse one or more RESP commands from a raw string.
    Returns a list of commands, each command being a list of string tokens.
    Handles both inline (plain text) and array (*) format.
    """
    commands = []
    i = 0
    lines = data.split("\r\n")       # RESP lines are always \r\n terminated

    while i < len(lines):
        line = lines[i]
        if not line:
            i += 1
            continue

        if line.startswith("*"):
            # Array format: *<count>  then alternating $<len> / <value> lines
            count = int(line[1:])
            tokens = []
            i += 1
            for _ in range(count):
                if i < len(lines) and lines[i].startswith("$"):
                    i += 1           # Skip the $<length> line
                if i < len(lines):
                    tokens.append(lines[i])
                    i += 1
            if tokens:
                commands.append(tokens)
        else:
            # Inline format: plain space-separated command  e.g. "PING"
            tokens = re.split(r"\s+", line.strip())
            if tokens and tokens[0]:
                commands.append(tokens)
            i += 1

    return commands


# ---------------------------------------------------------------------------
# 4.  COMMAND HANDLERS
# ---------------------------------------------------------------------------

def handle_command(tokens: list[str]) -> bytes:
    """
    Dispatch a parsed command to the right handler and return RESP bytes.
    All commands are case-insensitive (uppercased before matching).
    """
    if not tokens:
        return encode_error("empty command")

    cmd = tokens[0].upper()     # Normalize command name

    with store_lock:            # Hold the global mutex for the entire command

        # ---- Connection ----
        if cmd == "PING":
            msg = tokens[1] if len(tokens) > 1 else "PONG"
            return encode_simple(msg)

        if cmd == "QUIT":
            return encode_simple("OK")

        if cmd == "FLUSHALL":
            store.clear()
            expiry.clear()
            return encode_simple("OK")

        if cmd == "KEYS":
            pattern = tokens[1] if len(tokens) > 1 else "*"
            # Convert Redis glob pattern to Python regex
            regex = "^" + re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".") + "$"
            matched = [k for k in store if re.match(regex, k) and not is_expired(k)]
            return encode_array(matched)

        # ---- String / generic ----
        if cmd == "SET":
            if len(tokens) < 3:
                return encode_error("SET requires key and value")
            key, value = tokens[1], tokens[2]
            store[key] = value
            # Optional EX <seconds> suffix
            if len(tokens) >= 5 and tokens[3].upper() == "EX":
                expiry[key] = time.time() + int(tokens[4])
            elif key in expiry:
                del expiry[key]     # Remove old TTL if SET is called without EX
            return encode_simple("OK")

        if cmd == "GET":
            if len(tokens) < 2:
                return encode_error("GET requires key")
            key = tokens[1]
            if is_expired(key) or key not in store:
                return encode_bulk(None)
            val = store[key]
            if not isinstance(val, str):
                return encode_error("WRONGTYPE operation on wrong type")
            return encode_bulk(val)

        if cmd == "DEL":
            if len(tokens) < 2:
                return encode_error("DEL requires at least one key")
            count = 0
            for key in tokens[1:]:
                if key in store:
                    del store[key]
                    expiry.pop(key, None)
                    count += 1
            return encode_integer(count)

        if cmd == "EXISTS":
            if len(tokens) < 2:
                return encode_error("EXISTS requires key")
            key = tokens[1]
            exists = key in store and not is_expired(key)
            return encode_integer(1 if exists else 0)

        if cmd == "EXPIRE":
            if len(tokens) < 3:
                return encode_error("EXPIRE requires key and seconds")
            key, secs = tokens[1], int(tokens[2])
            if key not in store or is_expired(key):
                return encode_integer(0)
            expiry[key] = time.time() + secs
            return encode_integer(1)

        if cmd == "TTL":
            if len(tokens) < 2:
                return encode_error("TTL requires key")
            return encode_integer(ttl_seconds(tokens[1]))

        if cmd == "INCR":
            if len(tokens) < 2:
                return encode_error("INCR requires key")
            key = tokens[1]
            val = int(store.get(key, 0)) + 1    # Default to 0 if missing
            store[key] = str(val)
            return encode_integer(val)

        if cmd == "DECR":
            if len(tokens) < 2:
                return encode_error("DECR requires key")
            key = tokens[1]
            val = int(store.get(key, 0)) - 1
            store[key] = str(val)
            return encode_integer(val)

        # ---- List ----
        if cmd in ("LPUSH", "RPUSH"):
            if len(tokens) < 3:
                return encode_error(f"{cmd} requires key and value(s)")
            key = tokens[1]
            if key not in store:
                store[key] = []
            if not isinstance(store[key], list):
                return encode_error("WRONGTYPE operation on wrong type")
            for v in tokens[2:]:
                if cmd == "LPUSH":
                    store[key].insert(0, v)   # Prepend
                else:
                    store[key].append(v)      # Append
            return encode_integer(len(store[key]))

        if cmd in ("LPOP", "RPOP"):
            if len(tokens) < 2:
                return encode_error(f"{cmd} requires key")
            key = tokens[1]
            if key not in store or not isinstance(store[key], list):
                return encode_bulk(None)
            lst = store[key]
            if not lst:
                return encode_bulk(None)
            val = lst.pop(0) if cmd == "LPOP" else lst.pop()
            return encode_bulk(val)

        if cmd == "LRANGE":
            if len(tokens) < 4:
                return encode_error("LRANGE requires key start stop")
            key = tokens[1]
            start, stop = int(tokens[2]), int(tokens[3])
            if key not in store:
                return encode_array([])
            lst = store[key]
            # Redis supports negative indices (-1 = last element)
            length = len(lst)
            start = max(0, start + length if start < 0 else start)
            stop  = (stop + length if stop < 0 else stop) + 1   # inclusive → exclusive
            return encode_array(lst[start:stop])

        # ---- Hash ----
        if cmd == "HSET":
            if len(tokens) < 4 or len(tokens) % 2 != 0:
                return encode_error("HSET requires key field value [field value ...]")
            key = tokens[1]
            if key not in store:
                store[key] = {}
            if not isinstance(store[key], dict):
                return encode_error("WRONGTYPE operation on wrong type")
            added = 0
            pairs = tokens[2:]
            for j in range(0, len(pairs), 2):
                field, value = pairs[j], pairs[j + 1]
                if field not in store[key]:
                    added += 1
                store[key][field] = value
            return encode_integer(added)

        if cmd == "HGET":
            if len(tokens) < 3:
                return encode_error("HGET requires key and field")
            key, field = tokens[1], tokens[2]
            if key not in store or not isinstance(store[key], dict):
                return encode_bulk(None)
            return encode_bulk(store[key].get(field))

        if cmd == "HDEL":
            if len(tokens) < 3:
                return encode_error("HDEL requires key and field(s)")
            key = tokens[1]
            if key not in store or not isinstance(store[key], dict):
                return encode_integer(0)
            count = sum(1 for f in tokens[2:] if store[key].pop(f, None) is not None)
            return encode_integer(count)

        if cmd == "HGETALL":
            if len(tokens) < 2:
                return encode_error("HGETALL requires key")
            key = tokens[1]
            if key not in store or not isinstance(store[key], dict):
                return encode_array([])
            # Redis flattens field/value pairs into a single array
            flat = []
            for f, v in store[key].items():
                flat.extend([f, v])
            return encode_array(flat)

        return encode_error(f"unknown command '{cmd}'")


# ---------------------------------------------------------------------------
# 5.  CLIENT HANDLER (one thread per connection)
# ---------------------------------------------------------------------------

def handle_client(conn: socket.socket, addr: tuple) -> None:
    """
    Read data from a connected client in a loop, parse RESP commands,
    execute them, and write responses back — until the client disconnects
    or sends QUIT.
    """
    print(f"[+] Client connected: {addr}")
    buffer = ""     # Accumulate partial data between recv() calls

    try:
        while True:
            chunk = conn.recv(4096)          # Read up to 4 KB at a time
            if not chunk:
                break                        # Client closed the connection
            buffer += chunk.decode(errors="replace")

            # A complete RESP message always ends with \r\n
            if "\r\n" not in buffer:
                continue                     # Wait for more data

            commands = parse_resp(buffer)
            buffer = ""                      # Reset after parsing

            for tokens in commands:
                response = handle_command(tokens)
                conn.sendall(response)       # Send the RESP response back
                if tokens and tokens[0].upper() == "QUIT":
                    return                   # Gracefully close on QUIT
    except (ConnectionResetError, BrokenPipeError):
        pass                                 # Client disconnected abruptly
    finally:
        conn.close()
        print(f"[-] Client disconnected: {addr}")


# ---------------------------------------------------------------------------
# 6.  SERVER ENTRY POINT
# ---------------------------------------------------------------------------

def run_server(host: str = "127.0.0.1", port: int = 6379) -> None:
    """
    Bind a TCP socket on host:port and accept clients forever.
    Each client gets its own daemon thread so they don't block each other.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # SO_REUSEADDR lets us restart without waiting for the OS to release the port
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(128)          # Queue up to 128 pending connections
    print(f"mini-redis listening on {host}:{port}")

    try:
        while True:
            conn, addr = server.accept()    # Block until a client connects
            t = threading.Thread(
                target=handle_client,
                args=(conn, addr),
                daemon=True                 # Thread dies when main thread exits
            )
            t.start()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.close()


# ---------------------------------------------------------------------------
# 7.  START
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_server()
