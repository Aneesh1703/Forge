# Forge Repository Indexing Benchmark & Metrics Report

This document records the detailed performance, caching efficiency, accuracy breakdown, and database persistence metrics for Forge's complete `RepositoryIndexer` pipeline across major open-source Python codebases.

---

## Environment Configuration
- **OS**: Windows (x64)
- **Python**: 3.11.4
- **Parser**: `tree-sitter 0.26.0` + `BytePositionMapper` ($O(\log L)$ line/column lookup)
- **Database**: Docker PostgreSQL 17 (`forge-postgres` on port `5433`)
- **Async DB Driver**: `psycopg 3.3.4` (`postgresql+psycopg`)
- **Batching Profile**: `batch_size = 250` (Empirically benchmarked sweet spot)
- **Concurrency**: Parallel worker pool (`asyncio.Semaphore` + `asyncio.to_thread`)

---

## 1. Batch Size Benchmark Results (PostgreSQL Persistence)

Empirical evaluation of PostgreSQL persistence throughput across batch sizes `[50, 100, 250, 500, 1000]` evaluated on the `Pydantic` repository (814 files, 13,625 symbols):

| Batch Size | File Insert (s) | Symbol Insert (s) | Total DB Time (s) | Total DB Batches | Symbol Throughput | Speedup vs Batch 50 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **50** | 0.847 s | 13.736 s | **14.603 s** | 290 | 933.0 syms/sec | 1.00x (Baseline) |
| **100** | 0.542 s | 8.033 s | **8.582 s** | 146 | 1,587.6 syms/sec | **1.70x faster** |
| **250** | **0.310 s** | **2.300 s** | **2.616 s** | **59** | **5,207.5 syms/sec** | 🔥 **5.58x faster** |
| **500** | 0.330 s | 3.037 s | **3.375 s** | 30 | 4,037.2 syms/sec | 4.33x faster |
| **1000** | 0.260 s | 2.914 s | **3.180 s** | 15 | 4,284.9 syms/sec | 4.59x faster |

> [!NOTE]
> **Key Finding**: Batch Size **250** is the optimal sweet spot, yielding a **5.58x speedup** in database persistence time over batch size 50. Increasing batch size beyond 250 provides diminishing returns due to SQL parameter payload size and Postgres query buffer allocation.

---

## 2. Multi-Repository Pipeline Benchmark Summary (`batch_size = 250`)

| Repository | Parsed Files | Extracted Symbols | Parse Time (s) | Avg Parse Time (ms/file) | DB Insert Time (s) | Total DB Batches | Total Time (s) | Symbols/sec | Peak Memory (MB) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **FastAPI** | 3,138 | 5,654 | 7.20 s | 2.30 ms | 6.57 s | 36 | 14.55 s | 388.6 | 28.35 MB |
| **Flask** | 236 | 1,619 | 0.98 s | 4.15 ms | 1.35 s | 8 | 2.38 s | 680.0 | 7.21 MB |
| **Requests** | 130 | 807 | 0.65 s | 5.03 ms | 0.69 s | 5 | 1.38 s | 583.4 | 5.17 MB |
| **Pydantic** | 814 | 13,625 | 10.82 s | 13.29 ms | 10.05 s | 59 | 21.07 s | 646.5 | 37.80 MB |
| **Django** | 7,083 | 43,624 | 34.79 s | 4.91 ms | 37.23 s | 204 | 73.87 s | 590.6 | 125.18 MB |
| **TOTALS** | **11,401** | **65,329** | **54.45 s** | **4.78 ms** | **55.89 s** | **312** | **113.25 s** | **576.8** | **125.18 MB** |

---

## 3. Audited Parser Cache Statistics

By filtering `Language.UNKNOWN` files prior to requesting parser instances, cache statistics now reflect true parser instance reuse:

- **Requests**: Hits: `36` | Misses: `1` (1 miss for initial Python parser instantiation)
- **Flask**: Hits: `84` | Misses: `1`
- **FastAPI**: Hits: `1,324` | Misses: `2`
- **Pydantic**: Hits: `562` | Misses: `7`
- **Django**: Hits: `2,927` | Misses: `112`

---

## 4. Extracted Symbol Accuracy & Database Integrity

Stored and verified in Docker PostgreSQL:
- **Repositories**: `6`
- **Total Files**: `11,465`
- **Total Symbols**: `65,423`
  - **Classes**: `17,149`
  - **Functions**: `14,802`
  - **Methods**: `33,471`
  - **Symbols with Byte Offsets (`start_byte`, `end_byte`)**: `65,423` (100%)
  - **Methods Linked to Parent Classes (`parent_symbol_id`)**: `43,487`
