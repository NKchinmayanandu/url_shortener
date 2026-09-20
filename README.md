# Distributed URL Shortener Service

A production-grade, horizontally partitioned URL shortening and HTTP redirection service built with **FastAPI**, **Redis**, and **PostgreSQL**, deployed as a containerized stack via **Docker Compose** and load-balanced with **Nginx**.

---

## 1. Project Overview

### Purpose
This service provides high-throughput URL shortening and low-latency HTTP redirection. It takes long target URLs, generates compact 5-character alphanumeric identifiers, and serves HTTP 307 temporary redirects when the short identifiers are accessed.

### Architectural Goal
The primary objective of the architecture is to demonstrate scalable read/write separation and horizontal data partitioning without relying on centralized, monolithic database scaling. URL shortening workloads are overwhelmingly read-heavy: short links are generated once and redirected many thousands of times. The system addresses this asymmetric traffic pattern by combining:
- An in-memory **cache-aside layer** (Redis) to absorb repetitive redirect traffic.
- An application-managed **horizontal database sharding scheme** (PostgreSQL) to distribute write traffic, connection pooling, and disk storage across independent database nodes.

### Why Redis and PostgreSQL Sharding?
- **Redis Caching**: Serving HTTP redirects requires sub-millisecond retrieval. Hitting disk or executing relational queries on every redirect creates an unnecessary bottleneck on the database tier. Redis caches recently and frequently accessed mappings in-memory with a configurable Time-To-Live (TTL), bypassing the database on cache hits.
- **PostgreSQL Sharding**: Single-node relational databases inevitably encounter write saturation, connection pool exhaustion, and storage constraints as tables expand. By partitioning the URL dataset across multiple independent PostgreSQL instances using deterministic application-level hashing, write transactions, index trees, and connection overhead are evenly distributed.

---

## 2. Architecture

### System Topology

The platform consists of eight containerized services coordinated across an isolated Docker bridge network:
1. **Nginx Reverse Proxy**: Public-facing ingress on host port `8080`, performing Layer 7 round-robin load balancing across application worker instances.
2. **FastAPI Application Tier**: Three stateless, asynchronous application instances (`app-1`, `app-2`, `app-3`), each running on Uvicorn.
3. **Redis Cache**: A standalone Redis 8 instance (`redis-0`) acting as an in-memory cache-aside key-value store.
4. **PostgreSQL Shards**: Three independent PostgreSQL 18 instances (`postgres-0`, `postgres-1`, `postgres-2`), each responsible for one-third of the short-code keyspace.
5. **k6 Load Generator**: Dedicated container for running repeatable performance and stress tests within the internal network.

### Architecture Diagram

```
                              +-----------------------+
                              |      HTTP Clients     |
                              +-----------+-----------+
                                          |
                                          | Port 8080 (HTTP)
                                          v
                              +-----------------------+
                              |      Nginx Proxy      |
                              |   (Round-Robin L7)    |
                              +-----------+-----------+
                                          |
               +--------------------------+--------------------------+
               | (Port 8000)              | (Port 8000)              | (Port 8000)
               v                          v                          v
      +-----------------+        +-----------------+        +-----------------+
      |  FastAPI: app-1 |        |  FastAPI: app-2 |        |  FastAPI: app-3 |
      +--------+--------+        +--------+--------+        +--------+--------+
               |                          |                          |
               +--------------------------+--------------------------+
                                          |
               +--------------------------+--------------------------+
               |                                                     |
               | Cache Check / Populate                              | Deterministic Shard Routing
               | (Redis Protocol, Port 6379)                         | SHA-256(short_code) % 3
               v                                                     v
      +-----------------+                    +-----------------------+-----------------------+
      |  Redis Cache    |                    |                       |                       |
      |    (redis-0)    |             Shard 0|                Shard 1|                Shard 2|
      |   TTL: 300s     |                    v                       v                       v
      +-----------------+           +-----------------+     +-----------------+     +-----------------+
                                    |   postgres-0    |     |   postgres-1    |     |   postgres-2    |
                                    | (Shared-Nothing)|     | (Shared-Nothing)|     | (Shared-Nothing)|
                                    +--------+--------+     +--------+--------+     +--------+--------+
                                             |                       |                       |
                                             v                       v                       v
                                    [(postgres_0_data)]     [(postgres_1_data)]     [(postgres_2_data)]
```

### Key Architectural Principles
- **Nginx Ingress**: Nginx serves as the single reverse proxy for the cluster, terminating inbound client requests, passing client IP headers (`X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`), and distributing incoming HTTP traffic evenly among `app-1`, `app-2`, and `app-3`.
- **Stateless Application Layer**: The FastAPI application instances retain no local state. Any instance can process URL creations or redirects interchangeably.
- **Cache-Aside Pattern**: Read queries probe Redis first. Database shards are queried only on cache misses, after which the cache is backfilled.
- **Deterministic Shard Selection**: The target PostgreSQL instance is computed mathematically from the `short_code` itself using cryptographic hashing, removing the need for a central shard lookup directory or coordinator service.
- **Independent Shards (Shared-Nothing)**: The three PostgreSQL instances are **independent shards, not replicas**. There is no replication stream, shared storage, or consensus protocol (e.g., Raft/Paxos) between `postgres-0`, `postgres-1`, and `postgres-2`. Each shard maintains its own distinct dataset, transaction logs, and primary key namespace.

---

## 3. Request Flows

### 1. URL Creation Flow (`POST /shorten`)

```
Client             Nginx             FastAPI (app-N)          PostgreSQL (Shard N)       Redis (redis-0)
  |                  |                      |                          |                        |
  |--- POST /shorten |                      |                          |                        |
  |    ?url=... ---->|                      |                          |                        |
  |                  |--- Round-robin ----->|                          |                        |
  |                  |    proxy_pass        |                          |                        |
  |                  |                      |-- 1. generate 5-char code                         |
  |                  |                      |-- 2. shard = hash(code)%3                         |
  |                  |                      |                          |                        |
  |                  |                      |-- 3. INSERT url -------->|                        |
  |                  |                      |      (retry on collision)|                        |
  |                  |                      |<-- 4. Commit OK ---------|                        |
  |                  |                      |                                                   |
  |                  |                      |-- 5. SET code url EX 300 ------------------------>|
  |                  |                      |<-- 6. Cache populated (non-blocking) -------------|
  |                  |                      |                                                   |
  |                  |<-- JSON 200 ---------|                                                   |
  |<-- JSON 200 -----|    {short_code,      |                                                   |
  |    {short_url}   |     short_url}       |                                                   |
```

1. The client issues a `POST /shorten?url=https://example.com` request to Nginx on port `8080`.
2. Nginx forwards the request to an upstream application instance (`app-1`, `app-2`, or `app-3`).
3. The application generates a candidate 5-character alphanumeric short code using cryptographically secure random selection (`secrets.choice` across `[a-zA-Z0-9]`).
4. The application computes the deterministic shard index `shard = hash(short_code) % 3`.
5. The application acquires an asynchronous session for that shard from `session_makers[shard]` and attempts to persist the record. If a primary key collision occurs, the database raises an `IntegrityError`, caught by the application to retry generation with a new candidate code (up to 5 attempts).
6. Upon successful database commit, the application eagerly seeds the Redis cache with the mapping (`short_code` $\rightarrow$ `url`) with a 300-second TTL. If Redis is unreachable, the write operation still succeeds, logging a warning.
7. The application returns an `HTTP 200 OK` response containing the short code and the fully qualified redirect URL.

---

### 2. Redirect Cache-Hit Flow (`GET /{short_code}`)

```
Client             Nginx             FastAPI (app-N)               Redis (redis-0)        PostgreSQL Shards
  |                  |                      |                             |                       |
  |--- GET /{code} ->|                      |                             |                       |
  |                  |--- Round-robin ----->|                             |                       |
  |                  |    proxy_pass        |                             |                       |
  |                  |                      |-- 1. GET {short_code} ----->|                       |
  |                  |                      |<-- 2. Return original_url --|   (DB Shards Bypassed |
  |                  |                      |                                  Completely)        |
  |                  |<-- 307 Redirect -----|                             |                       |
  |<-- 307 Redirect -|    Location: <url>   |                             |                       |
```

1. The client issues a `GET /{short_code}` request to Nginx.
2. Nginx forwards the request to an application instance.
3. The application queries Redis for the key `short_code`.
4. **Cache Hit**: Redis returns the cached target URL immediately.
5. The application returns an `HTTP 307 Temporary Redirect` with the `Location` response header set to the target URL.
6. The entire database tier is completely bypassed. No database connections are checked out, and zero SQL queries are executed.

---

### 3. Redirect Cache-Miss Flow (`GET /{short_code}`)

```
Client             Nginx             FastAPI (app-N)          PostgreSQL (Shard N)       Redis (redis-0)
  |                  |                      |                          |                        |
  |--- GET /{code} ->|                      |                          |                        |
  |                  |--- Round-robin ----->|                          |                        |
  |                  |    proxy_pass        |                          |                        |
  |                  |                      |-- 1. GET {short_code} --------------------------->|
  |                  |                      |<-- 2. Key not found (MISS) -----------------------|
  |                  |                      |                                                   |
  |                  |                      |-- 3. shard = hash(code)%3                         |
  |                  |                      |-- 4. SELECT * FROM urls                               |
  |                  |                      |      WHERE code = :code ->|                       |
  |                  |                      |<-- 5. Return row --------|                        |
  |                  |                      |                                                   |
  |                  |                      |-- 6. SET code url EX 300 ------------------------>|
  |                  |                      |<-- 7. Cache set OK -------------------------------|
  |                  |                      |                                                   |
  |                  |<-- 307 Redirect -----|                                                   |
  |<-- 307 Redirect -|    Location: <url>   |                                                   |
```

1. The client issues a `GET /{short_code}` request.
2. Nginx forwards the request to an application instance.
3. The application queries Redis for `short_code`.
4. **Cache Miss**: Redis returns `None`.
5. The application calculates `shard = hash(short_code) % 3`.
6. The application checks out an async connection from the engine corresponding to that specific shard and executes:
   ```sql
   SELECT urls.short_code, urls.original_url, urls.created_at
   FROM urls
   WHERE urls.short_code = :short_code_1;
   ```
7. If the URL record does not exist, the service handles it accordingly.
8. If the record is found, the application writes the mapping back to Redis with a 300-second TTL (`ex=300`) to accelerate subsequent requests.
9. The application returns an `HTTP 307 Temporary Redirect` with the target URL in the `Location` header.

---

## 4. Database Architecture & Sharding

### Shard Key and Selection Algorithm
The shard key is the 5-character alphanumeric `short_code`. Shard assignment is calculated directly in Python using standard cryptographic hashing (`app/db/shard.py`):

```python
import hashlib

def hash_short_code(short_code: str) -> int:
    return int.from_bytes(
        hashlib.sha256(short_code.encode()).digest(),
        byteorder="big",
    )

def get_shard(short_code: str) -> int:
    hashed_code = hash_short_code(short_code=short_code)
    return hashed_code % 3
```

### Why Application-Level Shard Routing?
1. **Zero Intermediate Proxy Overhead**: By computing the shard destination directly within the application process, the architecture eliminates the latency and operational complexity of running separate SQL proxy layers (such as Vitess or Citus coordinators).
2. **Even Key Distribution**: SHA-256 exhibits avalanche properties—every character modification causes significant, pseudo-random changes in the resulting hash bits. Modulo 3 arithmetic across the resulting integer yields an exceptionally uniform distribution across shards.
   - *Empirical validation from live benchmark runs:*
     - Shard 0 (`postgres-0`): **3,995 rows** (~33.2%)
     - Shard 1 (`postgres-1`): **3,999 rows** (~33.3%)
     - Shard 2 (`postgres-2`): **4,024 rows** (~33.5%)
3. **Fault Isolation**: If a single database shard suffers disk failure or corruption, the remaining two shards continue to service reads and writes for two-thirds of the keyspace.

### Shared-Nothing Nature (No Distributed Replication)
It is critical to note that the PostgreSQL tier uses a **shared-nothing architecture without distributed replication**:
- Each shard runs as a standalone PostgreSQL daemon.
- No write-ahead log (WAL) shipping, logical replication, or cross-node synchronization is enabled.
- Data on `postgres-0` does not exist on `postgres-1` or `postgres-2`.
- Foreign keys and cross-shard queries are neither implemented nor supported.

### Asynchronous SQLAlchemy Engine Management
Each application instance initializes three independent asynchronous engines and session makers (`app/db/session.py`):

```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.core.config import settings

engines = [
    create_async_engine(settings.DATABASE_URL0, pool_size=10, max_overflow=20),
    create_async_engine(settings.DATABASE_URL1, pool_size=10, max_overflow=20),
    create_async_engine(settings.DATABASE_URL2, pool_size=10, max_overflow=20),
]

session_makers = [
    async_sessionmaker(engine, class_=AsyncSession)
    for engine in engines
]
```
Each engine maintains a dedicated connection pool (`pool_size=10`, `max_overflow=20`) to its respective PostgreSQL instance via `asyncpg`. When an operation targets Shard 1, it checks out a connection solely from `session_makers[1]`.

---

## 5. Caching Strategy

The cache layer (`app/redis/cache.py`) is implemented using `redis.asyncio` with the **cache-aside pattern** augmented by **proactive write warming**.

### Cache-Aside Mechanics
- **Read Path**: The application always inspects Redis before querying any database shard.
- **Write Path**: When a URL is created, the application writes to the target PostgreSQL shard first to ensure transactional durability, and then immediately populates Redis (`SET short_code url EX 300`). This ensures that the very first redirect request for a newly created URL is a cache hit.
- **TTL Expiration**: Every cached entry is assigned a strict 300-second (5-minute) TTL (`ex=300`).
  - *Rationale*: A bounded TTL prevents Redis memory exhaustion from inactive links and bounds cache inconsistency if an underlying database record were to be manually altered or removed.
- **Resilience to Cache Outages**: Cache interactions during URL creation are non-blocking:
  ```python
  try:
      await set_cache(short_code=short_code, url=url)
  except Exception:
      logging.warning("Redis cache population failed for short_code=%s", short_code, exc_info=True)
  ```
  If Redis is down or experiencing transient network partition, URL creation still succeeds because the database write has already committed.

---

## 6. Docker Topology & Networking

The system is defined entirely in [compose.yml](file:///home/chinmay/projects/fastapi/url_shortner/compose.yml).

### Service Manifest

| Service Name | Base Image | Role | Exposed Ports (Host:Container) | Storage / Mounts |
|---|---|---|---|---|
| `nginx` | `nginx:alpine` | Reverse proxy & L7 load balancer | `8080:80` | `./nginx/nginx.conf` (ro) |
| `app-1` | `url-shortener:local` | FastAPI ASGI worker replica 1 | Internal only (8000) | `.:/app` |
| `app-2` | `url-shortener:local` | FastAPI ASGI worker replica 2 | Internal only (8000) | `.:/app` |
| `app-3` | `url-shortener:local` | FastAPI ASGI worker replica 3 | Internal only (8000) | `.:/app` |
| `redis-0` | `redis:8` | In-memory key-value cache | Internal only (6379) | Ephemeral / container memory |
| `postgres-0` | `postgres:18` | Database Shard 0 | Internal only (5432) | `postgres_0_data:/var/lib/postgresql/data` |
| `postgres-1` | `postgres:18` | Database Shard 1 | Internal only (5432) | `postgres_1_data:/var/lib/postgresql/data` |
| `postgres-2` | `postgres:18` | Database Shard 2 | Internal only (5432) | `postgres_2_data:/var/lib/postgresql/data` |
| `k6` | `grafana/k6:latest` | Load testing client | None | `./k6:/scripts:ro` |

### Internal DNS and Network Isolation
- **Bridge Network**: All services connect to a single user-defined bridge network (`app-network`).
- **Service Name Resolution**: Containers communicate using Docker's embedded DNS server. Services reference each other by their Compose service identifiers (`postgres-0`, `postgres-1`, `postgres-2`, `redis-0`, `app-1`, `app-2`, `app-3`) rather than brittle, dynamic container IP addresses.
- **Port Isolation**: Only port `8080` (Nginx) is exposed to the host machine. Application instances, Redis, and PostgreSQL shard daemons are inaccessible from outside the Docker bridge network, mitigating unauthorized direct database and cache access.

### Persistent Named Volumes
PostgreSQL data directories are mounted to isolated named Docker volumes:
- `postgres_0_data` $\rightarrow$ `/var/lib/postgresql/data` on `postgres-0`
- `postgres_1_data` $\rightarrow$ `/var/lib/postgresql/data` on `postgres-1`
- `postgres_2_data` $\rightarrow$ `/var/lib/postgresql/data` on `postgres-2`

This guarantees that database state, transaction logs, and indexes persist across container restarts, image rebuilds, and `docker compose down` operations (unless explicitly dropped via `-v`).

---

## 7. Testing & Quality Assurance

The repository includes integration and end-to-end tests built with **pytest** and **pytest-asyncio** located in the `tests/` directory.

### Test Coverage

1. **Database Shard Testing** (`tests/test_db.py`):
   - `test_get_url_from_db`: Generates a random short code, deterministically calculates its target shard, performs a direct raw SQL insert via `session_makers[shard]`, and verifies that `url_repository.get_url()` retrieves the identical record from that specific shard.
2. **Cache Layer Testing** (`tests/test_cache.py`):
   - `test_set_and_get_cache`: Verifies asynchronous `set_cache` and `get_cache` operations against a live Redis instance.
   - `test_cache_has_ttl`: Verifies that cached keys are assigned a positive TTL that does not exceed 300 seconds (`0 < ttl <= 300`).
3. **End-to-End API Flow Testing** (`tests/test_url_flow.py`):
   - `test_shorten_and_redirect_flow`: Uses `httpx.AsyncClient` with `ASGITransport` against the FastAPI application. Sends a `POST /shorten?url=https://github.com` request, validates the `200 OK` status and returned short code, and immediately issues a `GET /{short_code}` (with `follow_redirects=False`) to verify that the application issues a `307 Temporary Redirect` with the proper `Location` header.

### Why Integration Tests Use Real Infrastructure (No Mocking)
The test suite deliberately executes against real, running instances of Redis and PostgreSQL rather than mocking database drivers or Redis clients. In distributed, asynchronous database architectures, mocks hide critical classes of bugs:
- **Event Loop & Connection Pool Binding**: The `asyncpg` driver binds connection pools and sockets to active asyncio event loops. Mocking obscures event loop lifecycle collisions and connection pool exhaustion.
- **SQL Dialect & Constraint Enforcement**: Mocks cannot validate foreign key constraints, primary key uniqueness violations (`IntegrityError`), server-side column defaults (`now()`), or driver-specific type coercions.
- **Hash Shard Routing**: End-to-end tests verify that URLs are routed to the mathematically correct database container out of the three active shards.
- **Cache TTL & Expiration Semantics**: Real Redis integration ensures that eviction policies, byte serialization/deserialization, and key lifetimes execute cleanly.

### Running the Tests

To ensure proper DNS resolution of `postgres-0`, `postgres-1`, `postgres-2`, and `redis-0`, run pytest inside an application container attached to `app-network`:

```bash
# Run database integration tests
docker compose exec app-1 python -m pytest tests/test_db.py

# Run cache integration tests
docker compose exec app-1 python -m pytest tests/test_cache.py

# Run end-to-end URL shortening and redirect integration tests
docker compose exec app-1 python -m pytest tests/test_url_flow.py
```

---

## 8. Performance Testing

The system was benchmarked using **Grafana k6** running as an independent container inside the Docker network.

> [!IMPORTANT]
> **Environment Specification**:
> - **Topology**: Docker Compose stack (Nginx, 3 FastAPI containers, Redis, 3 PostgreSQL shards, k6 runner)
> - **Execution Context**: Internal Docker bridge network (`app-network`) on a local developer machine
> - **Concurrency**: 10 Virtual Users (VUs)
> - **Network Latency**: Zero external WAN or Internet routing latency
> - **HTTP Failure Rate**: **0.00%** across all tests (100% check pass rate)

---

### Benchmark 1: URL Creation (`POST /shorten`)
Exercises the write path: random 5-character code generation, SHA-256 shard computation, PostgreSQL insert commit, and Redis cache warming.

- **Command**:
  ```bash
  docker compose run --rm k6 run /scripts/shorten.js
  ```
- **Configuration**: 10 VUs for 30 seconds
- **Requests Completed**: 10,998 HTTP requests
- **Throughput**: **366.09 req/s**
- **Latency**:
  - Average: **27.11 ms**
  - Median (p50): **42.79 ms**
  - p90: **47.58 ms**
  - p95: **49.14 ms**
  - Maximum: **200.94 ms**
- **HTTP Failure Rate**: **0.00%**
- **Checks Passed**: **100.00%**

---

### Benchmark 2: Redirect with Redis Cache Hit (`GET /{short_code}`)
Exercises the high-speed cached read path: Nginx load-balances to FastAPI, which retrieves the URL purely from Redis memory and immediately issues an HTTP 307 redirect.

- **Command**:
  ```bash
  docker compose run --rm k6 run /scripts/redirect-cache-hit.js
  ```
- **Configuration**: 10 VUs for 30 seconds
- **Requests Completed**: 259,922 HTTP requests
- **Throughput**: **8,663.80 req/s**
- **Latency**:
  - Average: **1.11 ms**
  - Median (p50): **0.935 ms**
  - p90: **2.09 ms**
  - p95: **2.55 ms**
  - Maximum: **15.79 ms**
- **HTTP Failure Rate**: **0.00%**
- **Checks Passed**: **100.00%**

---

### Benchmark 3: Redirect with PostgreSQL Read Path (`GET /{short_code}`)
Exercises the uncached database read path across all three shards. Pre-created database records were loaded into the database shards, and Redis was explicitly flushed (`FLUSHALL`) immediately prior to the test run. Every redirect represents a full cache miss that requires SHA-256 shard routing, connection pool checkout, and a SQL query to PostgreSQL. Setup requests are excluded from the metrics below.

- **Command**:
  ```bash
  docker compose run --rm k6 run /scripts/redirect-db.js
  ```
- **Configuration**: 10 VUs, 100 iterations per VU (`per-vu-iterations` executor)
- **Requests Completed**: 1,000 redirect requests
- **Throughput**: **1,627.51 req/s**
- **Latency**:
  - Average: **5.86 ms**
  - Median (p50): **2.51 ms**
  - p90: **16.42 ms**
  - p95: **27.88 ms**
  - Maximum: **92.65 ms**
- **HTTP Failure Rate**: **0.00%**
- **Checks Passed**: **100.00%**

---

### Performance Comparison Matrix

| Scenario | Path Exercised | Requests | Throughput | Avg Latency | p50 (Median) | p95 Latency | Max Latency | Error Rate |
|---|---|---|---|---|---|---|---|---|
| **Redirect (Cache Hit)** | Nginx $\rightarrow$ FastAPI $\rightarrow$ **Redis** | 259,922 | **8,663.80 req/s** | **1.11 ms** | **0.935 ms** | **2.55 ms** | 15.79 ms | 0.00% |
| **Redirect (Cache Miss)** | Nginx $\rightarrow$ FastAPI $\rightarrow$ **PostgreSQL** | 1,000 | **1,627.51 req/s** | **5.86 ms** | **2.51 ms** | **27.88 ms** | 92.65 ms | 0.00% |
| **URL Creation** | Nginx $\rightarrow$ FastAPI $\rightarrow$ **PostgreSQL Write** + Cache Set | 10,998 | **366.09 req/s** | **27.11 ms** | **42.79 ms** | **49.14 ms** | 200.94 ms | 0.00% |

### Analysis of Architectural Effects
1. **Redis In-Memory Absorption**: The Redis cache-hit path achieves **8,663.80 req/s** at an average latency of **1.11 ms** (~0.935 ms median). Bypassing relational queries, connection acquisition, and SQL parsing yields a **~5.3x throughput increase** and a **~5.3x latency reduction** compared to direct PostgreSQL reads.
2. **PostgreSQL Read Scalability**: Direct database reads across the shards sustained **1,627.51 req/s** with a median latency of **2.51 ms**. Sharding splits read traffic across three independent connection pools and memory buffers, allowing significant uncached read throughput.
3. **Database Write Bottleneck**: URL creation throughput is **366.09 req/s** with an average latency of **27.11 ms**. Writing to the database requires transaction initialization, primary key B-tree index insertion, WAL serialization to disk, commit acknowledgement, and subsequent Redis cache population. This confirms the classic RDBMS write penalty and underscores why read traffic must be shielded by Redis.

---

## 9. Performance Benchmark Limitations & Deployment Topology

### Benchmark Limitations
The numbers presented above reflect controlled, reproducible benchmarks within an isolated environment. They must not be misconstrued as production SLA guarantees:
- **No Internet or WAN Latency**: The client (k6) and server containers ran on the same host machine using an internal bridge network. Real-world client connections traverse public Internet backbones, cellular networks, and DNS resolution, which introduce 15 ms to 200+ ms of baseline round-trip time (RTT).
- **No TLS/HTTPS Overhead**: The benchmarks executed over plain HTTP. In production, TLS termination, SSL handshakes, and certificate negotiation consume additional CPU cycles and add latency.
- **Resource Contention**: In a shared cloud environment, noisy neighbors, CPU quota throttling, storage volume IOPS limits (e.g., AWS EBS volume bursting), and virtual network virtualization will impact tail latency (p95/p99).
- **Dataset Scale**: The benchmarks were executed against thousands of records. In enterprise production systems with tens or hundreds of millions of rows, index cache misses and table vacuuming require larger memory allocations.

### Single-VM vs. Multi-VM Deployment Considerations

#### Single-VM Deployment (Current Architecture)
This complete Docker Compose stack is well-suited for deployment on a **single sufficiently provisioned virtual machine** (e.g., 4–8 vCPUs, 16–32 GB RAM):
- **Advantages**: Colocating Nginx, FastAPI, Redis, and PostgreSQL shard containers on a single host eliminates cross-machine network hops. Inter-service latency operates over the Linux kernel's internal network stack (virtual bridge), minimizing serialization and socket overhead.
- **Suitability**: For small-to-moderate workloads (serving hundreds of writes and thousands of reads per second), a single robust VM provides maximum cost efficiency and minimal operational complexity.

#### When Multi-VM Deployment Becomes Necessary
A single VM represents a single failure domain and has vertical scaling limits. Transitioning to a multi-node architecture (e.g., via Kubernetes, Nomad, or discrete cloud VMs) is indicated when:
- **Independent Scaling**: Application instances need to scale dynamically based on CPU/traffic spikes without resizing the underlying database instances.
- **Hardware Specialization**: Database shards require high-IOPS NVMe storage volumes and large memory allocations for `shared_buffers`, while application instances require compute-optimized instances.
- **Fault Isolation & High Availability**: A host failure on a single VM takes down the entire service. Distributing the three PostgreSQL shards and Redis across separate availability zones or physical nodes prevents total service outages.

---

## 10. Deployment & Operations

### Prerequisites
- [Docker Engine](https://docs.docker.com/engine/install/) (v24.0+)
- [Docker Compose](https://docs.docker.com/compose/install/) (v2.20+)

### Environment Configuration
The application reads configuration from environment variables defined in `.env`. Create a `.env` file in the project root:

```ini
# Database Credentials
POSTGRES_USER=app_user
POSTGRES_PASSWORD=your_secure_password_here
POSTGRES_DB=urlshortener

# Asynchronous Shard Database URLs (asyncpg driver)
DATABASE_URL0=postgresql+asyncpg://app_user:your_secure_password_here@postgres-0:5432/urlshortener
DATABASE_URL1=postgresql+asyncpg://app_user:your_secure_password_here@postgres-1:5432/urlshortener
DATABASE_URL2=postgresql+asyncpg://app_user:your_secure_password_here@postgres-2:5432/urlshortener

# Redis Connection URL
REDIS_URL=redis://redis-0:6379
```

> [!WARNING]
> Never commit production passwords or credentials to version control. Ensure `.env` is listed in your `.gitignore`.

### Step-by-Step Deployment

#### 1. Build and Start the Docker Compose Stack
Launch all services in detached mode:
```bash
docker compose up -d --build
```

Verify that all 8 containers are healthy and running:
```bash
docker compose ps
```

#### 2. Apply Database Migrations Across All Shards
Because the three PostgreSQL containers are independent shards, schema migrations must be applied to each shard individually using Alembic's `-x shard=<index>` argument:

```bash
# Apply migrations to Shard 0 (postgres-0)
docker compose exec app-1 alembic -x shard=0 upgrade head

# Apply migrations to Shard 1 (postgres-1)
docker compose exec app-1 alembic -x shard=1 upgrade head

# Apply migrations to Shard 2 (postgres-2)
docker compose exec app-1 alembic -x shard=2 upgrade head
```

#### 3. Verify System Health
Query the public ingress endpoint to verify Nginx routing and FastAPI health:
```bash
curl -i http://localhost:8080/health
```
Expected response:
```json
{"status":"ok","instance":"app-1"}
```
Repeating this command will cycle through `"instance":"app-2"` and `"instance":"app-3"`, confirming that Nginx round-robin load balancing is operational.

---

## 11. API Specification

The API is exposed via Nginx on port `8080`.

### 1. Create Short URL
Generates a unique 5-character short code, assigns it to a database shard, commits the record, and populates the Redis cache.

- **Method**: `POST`
- **Path**: `/shorten`
- **Query Parameter**:
  - `url` (string, required): The target URL to shorten.
- **Example Request**:
  ```bash
  curl -X POST "http://localhost:8080/shorten?url=https://github.com/fastapi/fastapi"
  ```
- **Example Response** (`HTTP 200 OK`):
  ```json
  {
    "short_code": "xTxxJ",
    "short_url": "http://localhost:8080/xTxxJ"
  }
  ```

---

### 2. Redirect to Original URL
Resolves the short code against Redis (or falls back to the appropriate database shard) and returns an HTTP redirect.

- **Method**: `GET`
- **Path**: `/{short_code}`
- **Path Parameter**:
  - `short_code` (string, required): The 5-character identifier.
- **Example Request**:
  ```bash
  curl -i http://localhost:8080/xTxxJ
  ```
- **Example Response** (`HTTP 307 Temporary Redirect`):
  ```http
  HTTP/1.1 307 Temporary Redirect
  Server: nginx/1.27.x
  Date: Sun, 20 Sep 2026 12:00:00 GMT
  Content-Length: 0
  Connection: keep-alive
  Location: https://github.com/fastapi/fastapi
  ```

---

### 3. Service Health Check
Returns the availability status of the application worker instance and reports the handling container's `INSTANCE_ID`.

- **Method**: `GET`
- **Path**: `/health`
- **Example Request**:
  ```bash
  curl http://localhost:8080/health
  ```
- **Example Response** (`HTTP 200 OK`):
  ```json
  {
    "status": "ok",
    "instance": "app-2"
  }
  ```

---

## 12. Project Structure

```
.
├── Dockerfile                   # Python 3.12-slim base image with app dependencies
├── compose.yml                  # Multi-container Compose topology (Nginx, App, Redis, Postgres, k6)
├── requirements.txt             # Pinned Python package dependencies
├── alembic.ini                  # Alembic database migration configuration
├── .env                         # Local environment configuration (credentials, connection strings)
├── alembic/
│   ├── env.py                   # Custom migration runner with -x shard routing
│   └── versions/
│       └── 36d8dee83ec1_create_urls_table.py  # Initial table migration for 'urls'
├── app/
│   ├── main.py                  # FastAPI entry point, routing, and endpoint declarations
│   ├── core/
│   │   └── config.py            # Pydantic Settings management (.env parsing)
│   ├── db/
│   │   ├── base.py              # SQLAlchemy DeclarativeBase
│   │   ├── session.py           # Multi-engine connection pools (engines 0, 1, 2)
│   │   └── shard.py             # SHA-256 deterministic shard calculation (hash % 3)
│   ├── models/
│   │   └── urls.py              # SQLAlchemy 'urls' table model (short_code primary key)
│   ├── redis/
│   │   ├── redis_client.py      # Async Redis connection pool initialization
│   │   └── cache.py             # Cache-aside get/set helpers with 300s TTL
│   ├── repository/
│   │   └── url_repository.py    # Shard-directed database query and insert functions
│   ├── schemas/
│   │   └── shorten.py           # Pydantic request and response schemas
│   ├── services/
│   │   ├── redirect_service.py  # Redirect orchestration (Cache-aside -> Shard DB -> Cache set)
│   │   ├── unique_code.py       # Random 5-character alphanumeric token generator
│   │   └── url_service.py       # Shorten orchestration (retry loop, shard insert, cache warm)
│   └── utils/
│       └── logging.py           # Structured rotating file and stream logging setup
├── k6/
│   ├── shorten.js               # Load test script for POST /shorten
│   ├── redirect-cache-hit.js    # Benchmark script for cached GET /{short_code}
│   └── redirect-db.js           # Benchmark script for direct DB read path GET /{short_code}
├── nginx/
│   └── nginx.conf               # Upstream round-robin configuration and proxy headers
└── tests/
    ├── conftest.py              # Pytest async client and Redis fixtures
    ├── test_cache.py            # Integration tests for Redis operations and TTL
    ├── test_db.py               # Integration tests for direct shard insert/query
    └── test_url_flow.py         # End-to-end API tests for creation and redirection
```

---

## 13. Future Improvements

The following architectural enhancements represent natural extensions of the current design and are clearly distinguished as future engineering considerations:

1. **Edge Caching via CDN**:
   - Deploying an edge CDN (e.g., Cloudflare, CloudFront) in front of Nginx to cache HTTP 307 redirects globally. Highly viral links would be served directly from edge points of presence (PoPs), eliminating traffic to the origin cluster entirely.
2. **Redis High Availability & Clustering**:
   - Transitioning the standalone Redis instance to a **Redis Sentinel** deployment (for automatic primary-replica failover) or a **Redis Cluster** (for sharded in-memory key distribution) to remove Redis as a single point of failure.
3. **PostgreSQL High Availability & Read Replicas**:
   - Introducing streaming replication with Patroni and etcd for each shard, pairing each shard with a hot standby replica to enable zero-downtime failover and read-traffic offloading.
4. **Comprehensive Observability & Metrics**:
   - Integrating Prometheus middleware in FastAPI to export real-time request rates, p99 latencies, cache hit/miss ratios, and connection pool utilization into Grafana dashboards.
5. **Dynamic Shard Resharding**:
   - Implementing consistent hashing (such as a hash ring with virtual nodes) to allow adding database shards dynamically without requiring a full keyspace rehash.
6. **Automated Performance Regression CI**:
   - Embedding k6 performance test runs into CI/CD pipelines to catch latency regressions and connection leaks before code merges to production.
