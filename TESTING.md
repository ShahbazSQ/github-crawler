# Testing Guide

Complete guide to test your GitHub crawler locally before submitting.

## Prerequisites

- PostgreSQL installed and running
- Python 3.11+
- GitHub account (for API token)

## Quick Setup

```bash
# 1. Make setup script executable
chmod +x setup.sh

# 2. Run setup
./setup.sh

# 3. Edit .env file and add your GitHub token
nano .env
```

## Get GitHub Token

1. Go to https://github.com/settings/tokens
2. Click "Generate new token" → "Generate new token (classic)"
3. Give it a name: "GitHub Crawler Test"
4. **No special permissions needed** - default read access is enough
5. Click "Generate token"
6. Copy the token and paste into `.env` file

## Test Locally (Small Scale)

### Step 1: Test with 100 Repos

```bash
# Activate virtual environment
source venv/bin/activate

# Set small target for testing
export TARGET_REPO_COUNT=100

# Run crawler
python crawler.py
```

**Expected output:**
```
🚀 Starting crawl for 100 repositories...
📊 Fetched: 100/100 repos | Rate limit: 4900
✅ Crawl completed in 5.23 seconds
📈 Total repositories: 100
💾 Saved 100 repositories to JSON files
```

### Step 2: Insert into Database

```bash
python db_manager.py
```

**Expected output:**
```
✅ Connected to PostgreSQL
🏗️  Setting up database schema...
✅ Schema created successfully
💾 Inserting 100 repositories...
✅ Repositories inserted/updated successfully
📊 Inserting 100 statistics records...
✅ Statistics inserted successfully
🔄 Refreshing materialized view...
✅ Materialized view refreshed
📤 Exporting data to github_repos.csv...
✅ Data exported to github_repos.csv

📊 Database Summary:
   Total Repositories: 100
   Total Statistics Records: 100
   Average Stars: 50,234
   Max Stars: 450,123
   Min Stars: 5
```

### Step 3: Verify Data

```bash
# Connect to database
psql -d github_crawler_test

# Run test queries
SELECT COUNT(*) FROM github_data.repositories;
SELECT COUNT(*) FROM github_data.repo_statistics;

# Top 10 starred repos
SELECT full_name, star_count 
FROM github_data.repositories r
JOIN github_data.latest_repo_stats s ON r.repo_id = s.repo_id
ORDER BY star_count DESC 
LIMIT 10;
```

### Step 4: Check Generated Files

```bash
# Check CSV output
head -n 5 github_repos.csv

# Check JSON files
ls -lh repositories.json statistics.json

# Verify JSON structure
python3 -m json.tool repositories.json | head -n 20
```

## Test GitHub Actions Locally (Optional)

Use `act` to test GitHub Actions locally:

```bash
# Install act (macOS)
brew install act

# Test the workflow
act -j crawl-github-stars \
  --secret GITHUB_TOKEN=your_token_here \
  --env TARGET_REPO_COUNT=100

# This will:
# - Start PostgreSQL container
# - Run all workflow steps
# - Generate artifacts
```

## Performance Testing

### Test 1: Measure Crawl Speed

```bash
# Test with 1,000 repos
time python crawler.py
# Expected: 30-60 seconds

# Test with 10,000 repos
export TARGET_REPO_COUNT=10000
time python crawler.py
# Expected: 5-10 minutes
```

### Test 2: Database Performance

```bash
# Test insert performance
time python db_manager.py

# Check database size
psql -d github_crawler_test -c "\dt+ github_data.*"

# Test query performance
psql -d github_crawler_test -c "EXPLAIN ANALYZE 
  SELECT r.full_name, s.star_count 
  FROM github_data.repositories r
  JOIN github_data.latest_repo_stats s ON r.repo_id = s.repo_id
  ORDER BY s.star_count DESC 
  LIMIT 100;"
```

### Test 3: Rate Limit Handling

```bash
# Intentionally hit rate limits
export TARGET_REPO_COUNT=5000
python crawler.py

# Watch for rate limit messages:
# "⏳ Rate limit low. Waiting X seconds..."
# "Rate limit: 50" (getting low)
# Should auto-pause and resume
```

## Test Daily Updates

Simulate daily crawl to test update efficiency:

```bash
# Day 1: Initial crawl
python crawler.py
python db_manager.py

# Day 2: Re-crawl same repos (simulating daily update)
python crawler.py
python db_manager.py

# Verify:
# - repositories table: same count (upserted)
# - repo_statistics table: 2x count (new rows added)
psql -d github_crawler_test -c "
  SELECT 
    (SELECT COUNT(*) FROM github_data.repositories) as repo_count,
    (SELECT COUNT(*) FROM github_data.repo_statistics) as stats_count;
"

# Check historical data
psql -d github_crawler_test -c "
  SELECT repo_id, crawled_at, star_count
  FROM github_data.repo_statistics
  WHERE repo_id = (SELECT repo_id FROM github_data.repositories LIMIT 1)
  ORDER BY crawled_at DESC;
"
```

## Troubleshooting

### Issue: "GITHUB_TOKEN not found"

**Solution:**
```bash
# Check .env file exists
cat .env

# Export manually
export GITHUB_TOKEN="your_token_here"
```

### Issue: "Permission denied on database"

**Solution:**
```bash
# Grant permissions
psql -d github_crawler_test -c "
  GRANT ALL ON SCHEMA github_data TO $USER;
  GRANT ALL ON ALL TABLES IN SCHEMA github_data TO $USER;
"
```

### Issue: "Rate limit exceeded"

**Solution:**
- Wait for rate limit to reset (check output)
- Reduce TARGET_REPO_COUNT
- Use multiple GitHub accounts/tokens

### Issue: "Connection to PostgreSQL failed"

**Solution:**
```bash
# Check if PostgreSQL is running
pg_isready

# If not running (macOS):
brew services start postgresql

# If not running (Ubuntu):
sudo service postgresql start
```

## Pre-Submission Checklist

Before pushing to GitHub and submitting:

- [ ] Local test with 100 repos passes
- [ ] Local test with 1,000 repos passes
- [ ] Database schema created successfully
- [ ] CSV export works
- [ ] No hardcoded tokens in code
- [ ] `.env` file in `.gitignore`
- [ ] README is complete
- [ ] SCALING_AND_SCHEMA.md answers are thorough
- [ ] Code follows clean architecture principles
- [ ] Comments explain complex logic

## Push to GitHub

```bash
# Initialize git
git init

# Add files
git add .

# Commit
git commit -m "Initial commit: GitHub crawler implementation"

# Create GitHub repo (via web UI)
# Then push:
git remote add origin https://github.com/YOUR_USERNAME/github-crawler.git
git branch -M main
git push -u origin main
```

## Trigger GitHub Actions

1. Go to your repo on GitHub
2. Click "Actions" tab
3. Click "GitHub Crawler" workflow
4. Click "Run workflow"
5. Wait ~20-30 minutes for 100k repos
6. Check artifacts under workflow run

## Verify Submission

Final checks before submitting:

1. **GitHub Actions ran successfully** ✓
2. **Artifacts are downloadable** ✓
3. **CSV contains data** ✓
4. **README is clear** ✓
5. **Schema is in repo** ✓
6. **No secrets committed** ✓

## Expected Results

For 100,000 repositories:

- **Crawl time**: 20-30 minutes
- **Database size**: ~50MB
- **CSV size**: ~10MB
- **Rows in repositories**: 100,000
- **Rows in repo_statistics**: 100,000

## Questions?

If you encounter issues:

1. Check the logs
2. Verify your GitHub token
3. Test with smaller numbers first (100, 1000)
4. Check database permissions
5. Ensure PostgreSQL is running

Good luck! 🚀