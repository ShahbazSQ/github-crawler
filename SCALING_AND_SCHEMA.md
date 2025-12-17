# Scaling and Schema Evolution

This document answers the theoretical questions from the assignment.

## 1. Scaling to 500 Million Repositories

### Current System Limitations

With 100,000 repositories:
- **Crawl time**: ~20-30 minutes (respecting rate limits)
- **Database size**: ~50MB
- **Single instance**: One GitHub Actions runner

With 500 million repositories (5,000x increase):
- **Estimated crawl time**: 1,700+ hours (~71 days) on single instance
- **Database size**: ~250GB+
- **API calls**: 5 million GraphQL queries

### Proposed Architecture Changes

#### 1.1 Distributed Crawling System

**Worker Pool Architecture:**
```
┌─────────────────┐
│  Job Scheduler  │
│   (Coordinator) │
└────────┬────────┘
         │
    ┌────┴────┐
    │  Queue  │  (RabbitMQ/AWS SQS)
    └────┬────┘
         │
    ┌────┴──────────────────────┐
    │                           │
┌───▼────┐  ┌────────┐  ┌──────▼──┐
│Worker 1│  │Worker 2│  │Worker N │
└───┬────┘  └────┬───┘  └──────┬──┘
    │            │             │
    └────────────┴─────────────┘
               │
         ┌─────▼──────┐
         │ PostgreSQL │
         │  (Sharded) │
         └────────────┘
```

**Implementation:**
- Deploy 100+ crawler workers across AWS/GCP regions
- Each worker has own GitHub App with separate rate limits (5,000 points/hour each)
- Queue system distributes repo ID ranges to workers
- Workers report progress and failures back to coordinator

**Time Improvement:**
- 100 workers × 5,000 repos/hour = 500,000 repos/hour
- 500M repos ÷ 500K repos/hour = **1,000 hours (~42 days)**
- With more workers: potentially 10-20 hours

#### 1.2 Database Sharding Strategy

**Horizontal Partitioning:**

```sql
-- Shard by repo_id ranges
-- Shard 1: repo_id 0-100M
-- Shard 2: repo_id 100M-200M
-- Shard 3: repo_id 200M-300M
-- etc.

-- Use Citus or PostgreSQL partitioning
CREATE TABLE repositories (
    repo_id BIGINT,
    ...
) PARTITION BY RANGE (repo_id);

CREATE TABLE repositories_shard1 
    PARTITION OF repositories
    FOR VALUES FROM (0) TO (100000000);

CREATE TABLE repositories_shard2 
    PARTITION OF repositories
    FOR VALUES FROM (100000000) TO (200000000);
```

**Time-Series Partitioning for Statistics:**

```sql
-- Partition by crawl date for efficient queries
CREATE TABLE repo_statistics (
    repo_id BIGINT,
    crawled_at TIMESTAMP,
    ...
) PARTITION BY RANGE (crawled_at);

-- Monthly partitions
CREATE TABLE repo_statistics_2024_12
    PARTITION OF repo_statistics
    FOR VALUES FROM ('2024-12-01') TO ('2025-01-01');
```

**Benefits:**
- Query performance remains constant regardless of data size
- Old partitions can be moved to cheaper storage
- Parallel writes across shards
- Easy to add new shards as data grows

#### 1.3 Incremental Crawling Strategy

**Problem**: Crawling all 500M repos daily wastes resources

**Solution**: Smart incremental updates

```python
# Only crawl repos updated since last crawl
query = """
query {
  search(
    query: "pushed:>2024-12-15", 
    type: REPOSITORY, 
    first: 100
  ) {
    nodes {
      ... on Repository {
        id
        stargazerCount
        pushedAt
      }
    }
  }
}
"""
```

**Strategy:**
1. **Hot repos** (updated today): Crawl daily
2. **Warm repos** (updated this week): Crawl weekly
3. **Cold repos** (updated this month): Crawl monthly
4. **Archived repos**: Crawl quarterly

**Impact:**
- Reduces daily crawl volume by 80-90%
- From 500M to 50M repos per day
- Focuses resources on active repositories

#### 1.4 Caching and Read Optimization

**Multi-Layer Cache:**

```
User Query → CDN → Redis → Read Replica → Primary DB
```

**Implementation:**
- **Redis**: Cache top 100K most-starred repos (hot data)
- **Read Replicas**: 5-10 PostgreSQL read replicas for queries
- **CDN**: Static exports (CSV/JSON) cached at edge locations
- **Materialized Views**: Pre-computed aggregations

**Query Example:**
```sql
-- Materialized view refreshed hourly
CREATE MATERIALIZED VIEW top_repos_by_language AS
SELECT language, array_agg(full_name ORDER BY star_count DESC) as top_repos
FROM repositories r
JOIN latest_repo_stats s ON r.repo_id = s.repo_id
GROUP BY language;

-- Refresh in background
REFRESH MATERIALIZED VIEW CONCURRENTLY top_repos_by_language;
```

#### 1.5 Infrastructure as Code

**Kubernetes Deployment:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: github-crawler
spec:
  replicas: 100  # Scale horizontally
  template:
    spec:
      containers:
      - name: crawler
        image: github-crawler:latest
        env:
        - name: SHARD_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
```

**Auto-scaling:**
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: crawler-hpa
spec:
  scaleTargetRef:
    kind: Deployment
    name: github-crawler
  minReplicas: 10
  maxReplicas: 200
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

#### 1.6 Monitoring and Observability

**Metrics to Track:**
- Crawl rate (repos/second per worker)
- Queue depth (pending repos)
- Error rate (failed API calls)
- Database write latency
- Rate limit usage per worker

**Tools:**
- Prometheus + Grafana for metrics
- ELK Stack for log aggregation
- PagerDuty for alerts
- OpenTelemetry for distributed tracing

### Summary: 500M Scale Architecture

| Aspect | Current (100K) | Scaled (500M) |
|--------|---------------|---------------|
| Workers | 1 | 100+ |
| Crawl Time | 30 min | 10-20 hours |
| Database | Single PostgreSQL | Sharded + Replicas |
| Storage | 50MB | 250GB+ |
| Daily Updates | Full crawl | Incremental (10-20%) |
| Caching | None | Redis + CDN |
| Infrastructure | GitHub Actions | Kubernetes Cluster |

---

## 2. Schema Evolution for Additional Metadata

### Current Schema Strengths

✅ **Time-series approach**: Statistics tracked over time  
✅ **Separation of concerns**: Static vs dynamic data  
✅ **Efficient updates**: Minimal rows affected  
✅ **Foreign keys**: Data integrity maintained  

### Adding New Metadata Types

#### 2.1 Issues

**Schema Addition:**
```sql
CREATE TABLE github_data.issues (
    issue_id BIGINT PRIMARY KEY,
    repo_id BIGINT NOT NULL,
    issue_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    state VARCHAR(20),  -- 'open', 'closed'
    author_login VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    closed_at TIMESTAMP WITH TIME ZONE,
    comment_count INTEGER DEFAULT 0,
    reaction_count INTEGER DEFAULT 0,
    CONSTRAINT fk_issue_repo 
        FOREIGN KEY (repo_id) 
        REFERENCES github_data.repositories(repo_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_issues_repo ON github_data.issues(repo_id);
CREATE INDEX idx_issues_updated ON github_data.issues(updated_at DESC);
```

**Efficient Update Example:**

**Scenario**: Issue gets 10 new comments today, 20 more tomorrow

```sql
-- Day 1: Issue created with 10 comments
INSERT INTO github_data.issues 
(issue_id, repo_id, issue_number, title, state, comment_count, created_at)
VALUES (12345, 67890, 1, 'Bug Report', 'open', 10, NOW());

-- Day 2: 20 more comments added
-- Only 1 row affected!
UPDATE github_data.issues 
SET comment_count = 30, updated_at = NOW()
WHERE issue_id = 12345;
```

**No cascading updates needed!**

#### 2.2 Pull Requests

**Schema Addition:**
```sql
CREATE TABLE github_data.pull_requests (
    pr_id BIGINT PRIMARY KEY,
    repo_id BIGINT NOT NULL,
    pr_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    state VARCHAR(20),  -- 'open', 'closed', 'merged'
    author_login VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    merged_at TIMESTAMP WITH TIME ZONE,
    closed_at TIMESTAMP WITH TIME ZONE,
    comment_count INTEGER DEFAULT 0,
    review_count INTEGER DEFAULT 0,
    commit_count INTEGER DEFAULT 0,
    additions INTEGER DEFAULT 0,
    deletions INTEGER DEFAULT 0,
    changed_files INTEGER DEFAULT 0,
    CONSTRAINT fk_pr_repo 
        FOREIGN KEY (repo_id) 
        REFERENCES github_data.repositories(repo_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_prs_repo ON github_data.pull_requests(repo_id);
CREATE INDEX idx_prs_state ON github_data.pull_requests(state);
CREATE INDEX idx_prs_merged ON github_data.pull_requests(merged_at DESC) 
    WHERE merged_at IS NOT NULL;
```

#### 2.3 Comments (Unified Table)

**Schema Addition:**
```sql
CREATE TABLE github_data.comments (
    comment_id BIGINT PRIMARY KEY,
    parent_type VARCHAR(20) NOT NULL,  -- 'issue' or 'pull_request'
    parent_id BIGINT NOT NULL,
    author_login VARCHAR(255),
    body TEXT,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    reaction_count INTEGER DEFAULT 0
);

-- Composite index for efficient parent lookups
CREATE INDEX idx_comments_parent ON github_data.comments(parent_type, parent_id);
CREATE INDEX idx_comments_created ON github_data.comments(created_at DESC);
```

**Why unified table?**
- Comments on issues and PRs share same structure
- Easier to query all comments across types
- Reduces schema complexity
- Use `parent_type` discriminator for type safety

#### 2.4 PR Reviews

**Schema Addition:**
```sql
CREATE TABLE github_data.pr_reviews (
    review_id BIGINT PRIMARY KEY,
    pr_id BIGINT NOT NULL,
    reviewer_login VARCHAR(255),
    state VARCHAR(20),  -- 'APPROVED', 'CHANGES_REQUESTED', 'COMMENTED'
    submitted_at TIMESTAMP WITH TIME ZONE,
    body TEXT,
    comment_count INTEGER DEFAULT 0,
    CONSTRAINT fk_review_pr 
        FOREIGN KEY (pr_id) 
        REFERENCES github_data.pull_requests(pr_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_reviews_pr ON github_data.pr_reviews(pr_id);
CREATE INDEX idx_reviews_submitted ON github_data.pr_reviews(submitted_at DESC);
```

#### 2.5 Commits (in PRs)

**Schema Addition:**
```sql
CREATE TABLE github_data.commits (
    commit_sha VARCHAR(40) PRIMARY KEY,
    pr_id BIGINT,
    author_login VARCHAR(255),
    message TEXT,
    committed_at TIMESTAMP WITH TIME ZONE,
    additions INTEGER DEFAULT 0,
    deletions INTEGER DEFAULT 0,
    changed_files INTEGER DEFAULT 0,
    CONSTRAINT fk_commit_pr 
        FOREIGN KEY (pr_id) 
        REFERENCES github_data.pull_requests(pr_id)
        ON DELETE SET NULL
);

CREATE INDEX idx_commits_pr ON github_data.commits(pr_id);
CREATE INDEX idx_commits_author ON github_data.commits(author_login);
```

#### 2.6 CI/CD Checks

**Schema Addition:**
```sql
CREATE TABLE github_data.ci_checks (
    check_id BIGINT PRIMARY KEY,
    pr_id BIGINT NOT NULL,
    check_name VARCHAR(255),
    status VARCHAR(20),  -- 'pending', 'success', 'failure'
    conclusion VARCHAR(20),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT fk_check_pr 
        FOREIGN KEY (pr_id) 
        REFERENCES github_data.pull_requests(pr_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_checks_pr ON github_data.ci_checks(pr_id);
CREATE INDEX idx_checks_status ON github_data.ci_checks(status);
```

### Efficient Update Patterns

#### Pattern 1: Counter Updates

**Scenario**: PR comment count changes from 5 → 15 → 25

```sql
-- Single row update each time
UPDATE github_data.pull_requests 
SET 
    comment_count = comment_count + 10,
    updated_at = NOW()
WHERE pr_id = 12345;

-- Rows affected: 1 (extremely efficient!)
```

#### Pattern 2: Batch Inserts

**Scenario**: Crawl finds 100 new comments on various PRs

```sql
-- Batch insert using COPY or execute_batch
INSERT INTO github_data.comments 
(comment_id, parent_type, parent_id, author_login, body, created_at)
VALUES 
    (1001, 'pull_request', 123, 'user1', 'LGTM', NOW()),
    (1002, 'pull_request', 123, 'user2', 'Approved', NOW()),
    ... (98 more rows)
ON CONFLICT (comment_id) DO NOTHING;

-- Then update parent counters
UPDATE github_data.pull_requests 
SET comment_count = (
    SELECT COUNT(*) 
    FROM github_data.comments 
    WHERE parent_type = 'pull_request' 
      AND parent_id = pull_requests.pr_id
)
WHERE pr_id IN (123, 456, 789);
```

#### Pattern 3: Incremental Crawling

**Scenario**: Only fetch issues/PRs updated since last crawl

```python
# Store last crawl timestamp
last_crawl = get_last_crawl_time()

# Query only updated items
query = f"""
query {{
  repository(owner: "{owner}", name: "{name}") {{
    issues(first: 100, filterBy: {{since: "{last_crawl}"}}) {{
      nodes {{
        id
        number
        title
        comments {{
          totalCount
        }}
      }}
    }}
  }}
}}
"""
```

**Database Update:**
```sql
-- Upsert pattern for updated issues
INSERT INTO github_data.issues (issue_id, comment_count, updated_at)
VALUES (12345, 30, NOW())
ON CONFLICT (issue_id) 
DO UPDATE SET
    comment_count = EXCLUDED.comment_count,
    updated_at = EXCLUDED.updated_at;
```

### Schema Evolution Strategy

**Phase 1: Add Tables**
- Create new tables with foreign keys
- No impact on existing queries
- Backward compatible

**Phase 2: Populate Data**
- Backfill historical data in background
- Use batch inserts (1000 rows at a time)
- Monitor database load

**Phase 3: Add Indexes**
- Create indexes CONCURRENTLY (no table locks)
- Monitor query performance
- Adjust based on query patterns

**Phase 4: Optimize Queries**
- Create materialized views for complex joins
- Add partial indexes for common filters
- Use query result caching

### Example: Complete PR Data Model

```sql
-- Denormalized view for quick PR insights
CREATE MATERIALIZED VIEW github_data.pr_insights AS
SELECT 
    pr.pr_id,
    pr.title,
    pr.state,
    pr.comment_count,
    pr.review_count,
    pr.commit_count,
    COUNT(DISTINCT c.comment_id) as total_comments,
    COUNT(DISTINCT r.review_id) as total_reviews,
    COUNT(DISTINCT ci.check_id) as total_checks,
    COUNT(DISTINCT CASE WHEN ci.conclusion = 'success' THEN ci.check_id END) as passed_checks
FROM github_data.pull_requests pr
LEFT JOIN github_data.comments c ON c.parent_type = 'pull_request' AND c.parent_id = pr.pr_id
LEFT JOIN github_data.pr_reviews r ON r.pr_id = pr.pr_id
LEFT JOIN github_data.ci_checks ci ON ci.pr_id = pr.pr_id
GROUP BY pr.pr_id, pr.title, pr.state, pr.comment_count, pr.review_count, pr.commit_count;

-- Refresh daily
REFRESH MATERIALIZED VIEW CONCURRENTLY github_data.pr_insights;
```

### Performance Guarantees

| Operation | Rows Affected | Time Complexity |
|-----------|--------------|-----------------|
| Update PR comment count | 1 | O(1) |
| Insert new comment | 1 | O(1) |
| Add new review | 1 | O(1) |
| Batch insert 1000 comments | 1000 | O(n) |
| Query PR with all data | Variable | O(1) with proper indexes |

### Summary: Schema Evolution

✅ **Extensible**: Easy to add new tables  
✅ **Efficient**: Minimal rows affected on updates  
✅ **Performant**: Proper indexes and materialized views  
✅ **Maintainable**: Clear relationships via foreign keys  
✅ **Scalable**: Designed for millions of records  

The schema follows **normalized database design** principles while maintaining **query performance** through strategic **denormalization** (materialized views) where needed.