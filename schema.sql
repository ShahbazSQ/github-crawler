-- ============================================
-- GitHub Crawler Database Schema
-- ============================================
-- This schema is designed for:
-- 1. Efficient daily updates (upserts)
-- 2. Future extensibility (issues, PRs, comments)
-- 3. Minimal row updates when data changes
-- 4. Historical tracking of metrics
-- ============================================

-- Create schema for organization
CREATE SCHEMA IF NOT EXISTS github_data;

-- ============================================
-- CORE TABLES
-- ============================================

-- Main repositories table (relatively static data)
CREATE TABLE github_data.repositories (
    repo_id BIGINT PRIMARY KEY,                    -- GitHub's unique repo ID
    full_name VARCHAR(255) NOT NULL,               -- owner/repo-name
    owner_login VARCHAR(255) NOT NULL,             -- Repository owner username
    repo_name VARCHAR(255) NOT NULL,               -- Repository name
    description TEXT,                              -- Repo description
    html_url VARCHAR(500),                         -- GitHub URL
    created_at TIMESTAMP WITH TIME ZONE,           -- When repo was created
    is_fork BOOLEAN DEFAULT FALSE,                 -- Is this a fork?
    is_archived BOOLEAN DEFAULT FALSE,             -- Is archived?
    language VARCHAR(100),                         -- Primary language
    last_crawled_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(), -- Track crawl freshness
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()       -- Last update timestamp
);

-- Indexes for efficient lookups
CREATE INDEX idx_repos_full_name ON github_data.repositories(full_name);
CREATE INDEX idx_repos_owner ON github_data.repositories(owner_login);
CREATE INDEX idx_repos_last_crawled ON github_data.repositories(last_crawled_at);

-- ============================================
-- STATISTICS TABLE (Time-series data)
-- ============================================

-- Repository statistics - designed for efficient daily updates
-- This table uses a time-series approach for tracking changes
CREATE TABLE github_data.repo_statistics (
    repo_id BIGINT NOT NULL,                       -- Foreign key to repositories
    crawled_at TIMESTAMP WITH TIME ZONE NOT NULL,  -- When this data was collected
    star_count INTEGER NOT NULL DEFAULT 0,         -- Number of stars
    fork_count INTEGER DEFAULT 0,                  -- Number of forks
    watcher_count INTEGER DEFAULT 0,               -- Number of watchers
    open_issues_count INTEGER DEFAULT 0,           -- Open issues count
    PRIMARY KEY (repo_id, crawled_at),             -- Composite primary key
    CONSTRAINT fk_repo_stats_repo 
        FOREIGN KEY (repo_id) 
        REFERENCES github_data.repositories(repo_id)
        ON DELETE CASCADE
);

-- Indexes for time-based queries
CREATE INDEX idx_stats_crawled_at ON github_data.repo_statistics(crawled_at DESC);
CREATE INDEX idx_stats_star_count ON github_data.repo_statistics(star_count DESC);

-- ============================================
-- MATERIALIZED VIEW FOR LATEST STATS
-- ============================================

-- This view provides quick access to the most recent statistics
-- Useful for queries that don't need historical data
CREATE MATERIALIZED VIEW github_data.latest_repo_stats AS
SELECT DISTINCT ON (repo_id)
    repo_id,
    crawled_at,
    star_count,
    fork_count,
    watcher_count,
    open_issues_count
FROM github_data.repo_statistics
ORDER BY repo_id, crawled_at DESC;

-- Index on materialized view for fast lookups
CREATE UNIQUE INDEX idx_latest_stats_repo_id ON github_data.latest_repo_stats(repo_id);

-- ============================================
-- FUTURE EXTENSIBILITY TABLES
-- ============================================

-- Issues table (for future expansion)
CREATE TABLE github_data.issues (
    issue_id BIGINT PRIMARY KEY,                   -- GitHub issue ID
    repo_id BIGINT NOT NULL,                       -- Repository this belongs to
    issue_number INTEGER NOT NULL,                 -- Issue number (per repo)
    title TEXT NOT NULL,
    state VARCHAR(20),                             -- open, closed
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    closed_at TIMESTAMP WITH TIME ZONE,
    comment_count INTEGER DEFAULT 0,
    CONSTRAINT fk_issue_repo 
        FOREIGN KEY (repo_id) 
        REFERENCES github_data.repositories(repo_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_issues_repo ON github_data.issues(repo_id);
CREATE INDEX idx_issues_state ON github_data.issues(state);

-- Pull Requests table (for future expansion)
CREATE TABLE github_data.pull_requests (
    pr_id BIGINT PRIMARY KEY,                      -- GitHub PR ID
    repo_id BIGINT NOT NULL,                       -- Repository
    pr_number INTEGER NOT NULL,                    -- PR number (per repo)
    title TEXT NOT NULL,
    state VARCHAR(20),                             -- open, closed, merged
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    merged_at TIMESTAMP WITH TIME ZONE,
    comment_count INTEGER DEFAULT 0,
    review_count INTEGER DEFAULT 0,
    commit_count INTEGER DEFAULT 0,
    CONSTRAINT fk_pr_repo 
        FOREIGN KEY (repo_id) 
        REFERENCES github_data.repositories(repo_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_prs_repo ON github_data.pull_requests(repo_id);
CREATE INDEX idx_prs_state ON github_data.pull_requests(state);

-- Comments table (unified for issues and PRs)
CREATE TABLE github_data.comments (
    comment_id BIGINT PRIMARY KEY,                 -- GitHub comment ID
    parent_type VARCHAR(20) NOT NULL,              -- 'issue' or 'pull_request'
    parent_id BIGINT NOT NULL,                     -- Issue ID or PR ID
    author_login VARCHAR(255),
    body TEXT,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_comments_parent ON github_data.comments(parent_type, parent_id);

-- ============================================
-- CRAWL METADATA TABLE
-- ============================================

-- Track crawl runs for monitoring and debugging
CREATE TABLE github_data.crawl_runs (
    run_id SERIAL PRIMARY KEY,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    repos_crawled INTEGER DEFAULT 0,
    repos_failed INTEGER DEFAULT 0,
    status VARCHAR(20),                            -- running, completed, failed
    error_message TEXT
);

-- ============================================
-- HELPER FUNCTIONS
-- ============================================

-- Function to get latest star count for a repo
CREATE OR REPLACE FUNCTION github_data.get_latest_star_count(p_repo_id BIGINT)
RETURNS INTEGER AS $$
DECLARE
    v_star_count INTEGER;
BEGIN
    SELECT star_count INTO v_star_count
    FROM github_data.repo_statistics
    WHERE repo_id = p_repo_id
    ORDER BY crawled_at DESC
    LIMIT 1;
    
    RETURN COALESCE(v_star_count, 0);
END;
$$ LANGUAGE plpgsql;

-- Function to refresh materialized view (call after each crawl)
CREATE OR REPLACE FUNCTION github_data.refresh_latest_stats()
RETURNS VOID AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY github_data.latest_repo_stats;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- USEFUL QUERIES (for testing)
-- ============================================

-- Get top 10 most starred repos (latest crawl)
-- SELECT r.full_name, s.star_count
-- FROM github_data.repositories r
-- JOIN github_data.latest_repo_stats s ON r.repo_id = s.repo_id
-- ORDER BY s.star_count DESC
-- LIMIT 10;

-- Get star count history for a specific repo
-- SELECT crawled_at, star_count
-- FROM github_data.repo_statistics
-- WHERE repo_id = 123456
-- ORDER BY crawled_at DESC;

-- Get daily growth in stars
-- SELECT 
--     r.full_name,
--     s1.star_count - s2.star_count AS daily_growth
-- FROM github_data.repositories r
-- JOIN github_data.repo_statistics s1 ON r.repo_id = s1.repo_id
-- JOIN github_data.repo_statistics s2 ON r.repo_id = s2.repo_id
-- WHERE s1.crawled_at = CURRENT_DATE
--   AND s2.crawled_at = CURRENT_DATE - INTERVAL '1 day';