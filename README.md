# Redis 
> Remote Dictionary Server — an open-source, **in-memory** data store used as a database, cache, and message broker.

---

## What is Redis?

Redis stores all data in **RAM**, making it blazingly fast (sub-millisecond latency). Created in 2009 by Salvatore Sanfilippo, it's used by Instagram, Twitter, GitHub, and more.

---

## Data Types

| Type | Description | Example |
|------|-------------|---------|
| **String** | Text, numbers, binary | `SET name "Alice"` |
| **List** | Ordered, duplicates allowed | `LPUSH queue task1` |
| **Set** | Unique members only | `SADD tags "python"` |
| **Sorted Set** | Members with scores | `ZADD board 100 "Alice"` |
| **Hash** | Field-value pairs | `HSET user name Alice` |
| **Stream** | Append-only log | `XADD events * key val` |

---

## Core Commands

```bash
# Strings
SET key value          # store a value
GET key                # retrieve a value
DEL key                # delete a key
INCR counter           # atomic increment

# Expiry
SET session abc EX 3600   # auto-delete after 1 hour
TTL key                   # check time remaining

# Lists
LPUSH queue task1      # push to front
RPOP queue             # pop from back
BRPOP queue 0          # blocking pop (waits for data)

# Sets
SADD myset "a"         # add member
SMEMBERS myset         # list all members
SINTER set1 set2       # intersection

# Sorted Sets
ZADD leaderboard 100 "Alice"     # add with score
ZREVRANGE leaderboard 0 9        # top 10

# Hashes
HSET user name "Alice" age 30    # set fields
HGETALL user                     # get all fields

# Pub/Sub
PUBLISH channel message          # publish
SUBSCRIBE channel                # subscribe

# Transactions
MULTI                  # begin
SET key val            # queue command
EXEC                   # run all at once
```

---

## How It Works

```
Clients ──TCP/RESP──► Event Loop (single-threaded) ──► In-memory Dict
                                                              │
                                                      (optional disk)
                                                       ├── RDB snapshot
                                                       └── AOF log
```

- **Single-threaded** — processes one command at a time, no locking needed
- **In-memory** — all data lives in RAM; reads are direct memory lookups
- **RESP protocol** — simple text-based wire format (easy to implement in any language)

---

## Persistence

| Mode | How | Trade-off |
|------|-----|-----------|
| **RDB** | Point-in-time snapshots to disk | Fast restore, may lose recent data |
| **AOF** | Logs every write command | Safer, larger file |
| **Both** | RDB + AOF combined | Best of both worlds |

---

## Key Features

- **TTL / Expiry** — keys auto-delete after a set time
- **Pub/Sub** — real-time messaging between clients
- **Pipelining** — batch commands to reduce network round-trips
- **Lua scripting** — atomic server-side scripts
- **Transactions** — `MULTI/EXEC` command batching

---

## Redis vs SQL

| | Redis | SQL DB |
|---|---|---|
| Storage | RAM | Disk |
| Speed | Microseconds | Milliseconds |
| Model | Key-value + types | Relational tables |
| Queries | By key only | Full SQL |
| Persistence | Optional | Always |
| Best for | Cache, sessions, queues | Long-term structured data |

---

## Common Use Cases

- **Caching** — avoid repeated expensive DB queries
- **Session storage** — fast reads + auto-expiry with TTL
- **Rate limiting** — `INCR` + `EXPIRE` per user per window
- **Leaderboards** — Sorted Sets with `ZADD` / `ZREVRANGE`
- **Job queues** — `LPUSH` to enqueue, `BRPOP` to consume
- **Real-time analytics** — counters, unique visitors, time-series

---

## Scaling

- **Replication** — primary writes, replicas handle reads
- **Redis Sentinel** — auto-failover if primary goes down
- **Redis Cluster** — shards data across nodes via 16,384 hash slots

---

## Wire Protocol (RESP)

```
*3\r\n     ← 3 elements in array
$3\r\n
SET\r\n
$4\r\n
name\r\n
$5\r\n
Alice\r\n
```

Each message starts with a type byte: `+` string, `-` error, `:` integer, `$` binary, `*` array.

---

## Quick Start

```bash
# Install (Ubuntu)
sudo apt install redis-server

# Start server
redis-server

# Connect via CLI
redis-cli

# Ping test
127.0.0.1:6379> PING
PONG
```

---

## Resources

- [Official Docs](https://redis.io/docs/)
- [Redis Commands](https://redis.io/commands/)
- [Try Redis Online](https://try.redis.io/)
- [Building a mini Redis in Python](https://charlesleifer.com/blog/building-a-simple-redis-server-with-python/)
