# GitHub Repository Crawler

A high-performance crawler that fetches star counts from 100,000 GitHub repositories using GraphQL API and stores them efficiently in PostgreSQL.

## 🚀 Features

- **Fast Crawling**: Uses GitHub's GraphQL API with concurrent requests
- **Rate Limit Handling**: Automatic retry mechanism with exponential backoff
- **Efficient Storage**: Time-series approach for minimal database updates
- **Daily Automation**: GitHub Actions workflow for continuous crawling
- **Clean Architecture**: Separation of concerns, anti-corruption layer, immutability
- **Future-Ready**: Schema designed for extensibility (issues, PRs, comments)

## 📁 Project Structure

```
.
├── .github/
│   └── workflows/
│       └── crawl.yml          # GitHub Actions workflow
├── crawler.py                 # Main crawler logic
├── db_manager.py              # Database operations
├── schema.sql                 # PostgreSQL schema
├── requirements.txt           # Python dependencies
└── README.md                  # This file
```

## 🏗️ Architecture

### Clean Architecture Principles

1. **Anti-Corruption Layer**: `GitHubGraphQLClient` isolates GitHub API complexity
2. **Domain Mapping**: `RepositoryMapper` transforms API responses to domain models
3. **Separation of Concerns**: Crawler, database, and API logic are separate
4. **Immutability**: Data structures are treated as immutable where possible

### Database Schema Design

**Key Design Decisions:**

1. **Separation of Static vs Dynamic Data**
   - `repositories` table: Static info (name, owner, language)
   - `repo_statistics` table: Time-series data (stars, forks)

2. **Time-Series Approach**
   - Every crawl inserts new statistics rows (no updates needed)
   - Tracks historical changes in star counts
   - Minimal rows affected during daily updates

3. **Materialized View**
   - `latest_repo_stats` provides instant access to current data
   - Refreshed after each crawl for optimal query performance

## 🚀 Quick Start

### Local Testing

1. **Install PostgreSQL**:
```bash
# macOS
brew install postgresql
brew services start postgresql

# Ubuntu
sudo apt-get install postgresql
sudo service postgresql start
```

2. **Create Database**:
```bash
createdb github_crawler
psql github_crawler < schema.sql
```

3. **Install Python Dependencies**:
```bash
pip install -r requirements.txt
```

4. **Set Environment Variables**:
```bash
export GITHUB_TOKEN="your_github_token"
export POSTGRES_HOST="localhost"
export POSTGRES_DB="github_crawler"
export POSTGRES_USER="postgres"
export POSTGRES_PASSWORD="postgres"
export TARGET_REPO_COUNT="1000"  # Start small for testing
```

5. **Run Crawler**:
```bash
python crawler.py
python db_manager.py
```

### GitHub Actions

The workflow automatically runs when:
- You trigger it manually from the Actions tab
- Daily at midnight UTC (scheduled)

**No setup required** - uses default `GITHUB_TOKEN` with no elevated permissions.

## 📊 Performance

### Crawl Speed

- **Target**: 100,000 repositories
- **Rate Limit**: 5,000 GraphQL points/hour
- **Batch Size**: 100 repos per query
- **Expected Duration**: ~20-30 minutes (respecting rate limits)

### Database Efficiency

**Daily Update Operations:**
- New star count: **1 INSERT** in `repo_statistics` (not UPDATE)
- Repository metadata: **1 UPSERT** in `repositories`
- Total rows affected: **2 per repository** (minimal!)

## 🔮 Future Scalability

### Handling 500 Million Repositories

If this system needed to scale to 500 million repos:

1. **Distributed Crawling**
   - Deploy multiple crawler instances across regions
   - Partition repos by ID ranges (0-100M, 100M-200M, etc.)
   - Use message queue (RabbitMQ/Kafka) for coordination

2. **Database Partitioning**
   - Partition `repo_statistics` by `crawled_at` (monthly partitions)
   - Shard `repositories` by `repo_id` ranges across multiple databases
   - Use Citus or PostgreSQL native partitioning

3. **Incremental Updates**
   - Only crawl repos that have been updated since last crawl
   - Use GitHub's `updated_at` field for filtering
   - Reduce API calls by 80-90%

4. **Caching & CDN**
   - Cache popular repos in Redis
   - Use read replicas for analytics queries
   - Deploy CDN for static data exports

5. **Infrastructure**
   - Kubernetes for orchestration
   - Auto-scaling based on queue depth
   - Separate read/write database instances

### Schema Evolution for Additional Metadata

The schema is designed for easy extension:

```sql
-- Already included in schema.sql:

-- Issues table
CREATE TABLE github_data.issues (
    issue_id BIGINT PRIMARY KEY,
    repo_id BIGINT REFERENCES repositories,
    issue_number INTEGER,
    comment_count INTEGER,  -- Updated daily
    ...
);

-- Pull Requests table
CREATE TABLE github_data.pull_requests (
    pr_id BIGINT PRIMARY KEY,
    repo_id BIGINT REFERENCES repositories,
    pr_number INTEGER,
    comment_count INTEGER,
    review_count INTEGER,
    commit_count INTEGER,
    ...
);

-- Comments table (unified)
CREATE TABLE github_data.comments (
    comment_id BIGINT PRIMARY KEY,
    parent_type VARCHAR(20),  -- 'issue' or 'pull_request'
    parent_id BIGINT,
    body TEXT,
    ...
);
```

**Efficient Updates:**
- When PR gets 10 new comments: **1 UPDATE** to `pull_requests.comment_count`
- New comment posted: **1 INSERT** to `comments` table
- No cascading updates or full table scans needed

**Adding New Metadata:**
1. Create new table (e.g., `ci_checks`, `reviews`)
2. Add foreign key to `repositories` or `pull_requests`
3. Update crawler to fetch new data
4. Existing data remains untouched

## 🔧 Technologies Used

- **Language**: Python 3.11
- **API**: GitHub GraphQL API v4
- **Database**: PostgreSQL 15
- **Async I/O**: aiohttp, asyncio
- **Retry Logic**: tenacity
- **CI/CD**: GitHub Actions

## 📈 Monitoring

The system includes:
- `crawl_runs` table tracks each execution
- Rate limit monitoring in crawler logs
- Database statistics via `get_stats_summary()`
- GitHub Actions logs for debugging

## 🤝 Contributing

This is an assignment submission, but feel free to fork and improve!

## 📄 License

MIT License - See LICENSE file for details

---

**Author**: [Your Name]  
**Assignment**: GitHub Crawler for [Company Name]  
**Date**: December 2024