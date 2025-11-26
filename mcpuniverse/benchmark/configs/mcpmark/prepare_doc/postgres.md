# PostgreSQL

This guide walks you through preparing your PostgreSQL environment for MCPMark (adapted for MCP-Universe framework).

## 1 · Setup PostgreSQL Environment

### 1.1 Check Current Status

```bash
python mcpmark/prepare_scripts/check_postgres.py
```

This will show you:
- ✅/❌ Docker running status
- ✅/❌ PostgreSQL container status
- ✅/❌ Database status (chinook, employees, dvdrental, sports)

### 1.2 Run Setup (One-Time)

```bash
./mcpmark/prepare_scripts/setup_postgres.sh
```

Or use Python directly:

```bash
python mcpmark/prepare_scripts/prepare_postgres.py
```

This will:
1. Check Docker is running
2. Start PostgreSQL container (if needed)
3. Download database backup files from https://storage.mcpmark.ai/postgres/
4. Create 4 databases: chinook, employees, dvdrental, sports
5. Restore from backup files and verify tables

**Expected output:**
```
============================================================
📊 Summary
============================================================
✅ chinook       -  11 tables
✅ employees     -   6 tables
✅ dvdrental     -  15 tables
✅ sports        -  28 tables
------------------------------------------------------------
✅ All databases prepared successfully!

📝 PostgreSQL Configuration:
   Host: localhost
   Port: 5432
   User: postgres
   Password: password
   Databases: chinook, employees, dvdrental, sports

🚀 You can now run the mcpmark postgres benchmarks!
```

---

## 2 · Configure Environment Variables

Add the following PostgreSQL credentials to your `.env` file:

```env
## PostgreSQL Configuration
POSTGRES_ADDRESS=postgresql://postgres:password@localhost:5432
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USERNAME=postgres
POSTGRES_PASSWORD=password
```

**Note**: The database name in `POSTGRES_ADDRESS` will be automatically changed per task by `mcpuniverse/benchmark/prepares.py`.

---

## 3 · Running PostgreSQL Tasks

```bash
python tests/benchmark/test_benchmark_mcpmark_postgres.py
```

---

## 4 · Container Management

### View Logs
```bash
docker logs mcpmark-postgres
```

### Stop Container
```bash
docker stop mcpmark-postgres
```

### Start Container
```bash
docker start mcpmark-postgres
```

### Remove Container (Clean Reset)
```bash
docker stop mcpmark-postgres
docker rm mcpmark-postgres
# Then run setup again
./mcpmark/prepare_scripts/setup_postgres.sh
```

---

## 5 · Advanced Usage

### Force Re-download Databases

```bash
python mcpmark/prepare_scripts/prepare_postgres.py --force-download
```

### Setup Specific Databases Only

```bash
# Single database
python mcpmark/prepare_scripts/prepare_postgres.py --databases chinook

# Multiple databases
python mcpmark/prepare_scripts/prepare_postgres.py --databases chinook employees

# All databases (default)
python mcpmark/prepare_scripts/prepare_postgres.py --databases all
```

---

## 6 · What Gets Created

### Files Downloaded
```
tests/data/postgres/
├── chinook.backup      # Music store database
├── employees.backup    # Employee management
├── dvdrental.backup    # DVD rental store
└── sports.backup       # Sports statistics
```

### Docker Container
```
Name:     mcpmark-postgres
Image:    postgres:17-alpine
Port:     5432 (localhost)
User:     postgres
Password: password
```

### Databases
```
┌──────────────┬────────┬───────────────────────────┐
│ Database     │ Tables │ Description               │
├──────────────┼────────┼───────────────────────────┤
│ chinook      │ 11     │ Music store (tracks,      │
│              │        │ albums, customers)        │
├──────────────┼────────┼───────────────────────────┤
│ employees    │ 6      │ Employee management       │
│              │        │ (salaries, departments)   │
├──────────────┼────────┼───────────────────────────┤
│ dvdrental    │ 15     │ DVD rental store          │
│              │        │ (films, rentals, payments)│
├──────────────┼────────┼───────────────────────────┤
│ sports       │ 28     │ Sports statistics         │
│              │        │ (players, teams, games)   │
└──────────────┴────────┴───────────────────────────┘
```
