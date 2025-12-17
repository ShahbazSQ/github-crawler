"""
GitHub Crawler - Fetches 100k repos with star counts
Features:
- GraphQL API for efficiency
- Rate limit handling with retries
- Concurrent requests for speed
- Clean architecture with separation of concerns
"""
from dotenv import load_dotenv
load_dotenv() 
import asyncio
import aiohttp
import os
import time
from datetime import datetime
from typing import List, Dict, Optional
from tenacity import retry, stop_after_attempt, wait_exponential
import json


class GitHubGraphQLClient:
    """Anti-corruption layer for GitHub GraphQL API"""
    
    BASE_URL = "https://api.github.com/graphql"
    REPOS_PER_QUERY = 100  # Max repos per GraphQL query
    
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limit_remaining = 5000
        self.rate_limit_reset_at = 0
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers=self.headers)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def _build_search_query(self, cursor: Optional[str] = None) -> str:
        """Build GraphQL query for repository search"""
        after_clause = f', after: "{cursor}"' if cursor else ""
        
        return """
        query {
          search(query: "stars:>1", type: REPOSITORY, first: 100%s) {
            pageInfo {
              hasNextPage
              endCursor
            }
            nodes {
              ... on Repository {
                databaseId
                nameWithOwner
                owner {
                  login
                }
                name
                description
                url
                createdAt
                isFork
                isArchived
                primaryLanguage {
                  name
                }
                stargazerCount
                forkCount
                watchers {
                  totalCount
                }
                issues(states: OPEN) {
                  totalCount
                }
              }
            }
          }
          rateLimit {
            remaining
            resetAt
          }
        }
        """ % after_clause
    
    async def _check_rate_limit(self):
        """Check and wait if rate limit is low"""
        if self.rate_limit_remaining < 100:
            wait_time = max(0, self.rate_limit_reset_at - time.time())
            if wait_time > 0:
                print(f"⏳ Rate limit low. Waiting {wait_time:.0f} seconds...")
                await asyncio.sleep(wait_time + 5)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    async def fetch_repositories(self, cursor: Optional[str] = None) -> Dict:
        """Fetch a batch of repositories with retry mechanism"""
        await self._check_rate_limit()
        
        query = self._build_search_query(cursor)
        payload = {"query": query}
        
        async with self.session.post(self.BASE_URL, json=payload) as response:
            if response.status == 200:
                data = await response.json()
                
                # Update rate limit info
                if "data" in data and "rateLimit" in data["data"]:
                    rate_limit = data["data"]["rateLimit"]
                    self.rate_limit_remaining = rate_limit["remaining"]
                    reset_at = rate_limit["resetAt"]
                    self.rate_limit_reset_at = datetime.fromisoformat(
                        reset_at.replace("Z", "+00:00")
                    ).timestamp()
                
                return data
            elif response.status == 403:
                print(f"⚠️  Rate limit hit. Status: {response.status}")
                await asyncio.sleep(60)
                raise Exception("Rate limit exceeded")
            else:
                error_text = await response.text()
                print(f"❌ API Error: {response.status} - {error_text}")
                raise Exception(f"API request failed: {response.status}")


class RepositoryMapper:
    """Maps GitHub API response to domain models"""
    
    @staticmethod
    def map_to_repository(node: Dict) -> Dict:
        """Transform API response to repository dict"""
        return {
            "repo_id": node.get("databaseId"),
            "full_name": node.get("nameWithOwner"),
            "owner_login": node.get("owner", {}).get("login"),
            "repo_name": node.get("name"),
            "description": node.get("description"),
            "html_url": node.get("url"),
            "created_at": node.get("createdAt"),
            "is_fork": node.get("isFork", False),
            "is_archived": node.get("isArchived", False),
            "language": node.get("primaryLanguage", {}).get("name") if node.get("primaryLanguage") else None,
        }
    
    @staticmethod
    def map_to_statistics(node: Dict, crawled_at: datetime) -> Dict:
        """Transform API response to statistics dict"""
        return {
            "repo_id": node.get("databaseId"),
            "crawled_at": crawled_at,
            "star_count": node.get("stargazerCount", 0),
            "fork_count": node.get("forkCount", 0),
            "watcher_count": node.get("watchers", {}).get("totalCount", 0),
            "open_issues_count": node.get("issues", {}).get("totalCount", 0),
        }


class GitHubCrawler:
    """Main crawler orchestrator"""
    
    def __init__(self, github_client: GitHubGraphQLClient, target_count: int = 100000):
        self.client = github_client
        self.target_count = target_count
        self.repositories: List[Dict] = []
        self.statistics: List[Dict] = []
    
    async def crawl(self) -> tuple[List[Dict], List[Dict]]:
        """
        Crawl GitHub repositories
        Returns: (repositories, statistics)
        """
        print(f"🚀 Starting crawl for {self.target_count} repositories...")
        start_time = time.time()
        
        cursor = None
        total_fetched = 0
        crawled_at = datetime.utcnow()
        
        while total_fetched < self.target_count:
            try:
                # Fetch batch
                response = await self.client.fetch_repositories(cursor)
                
                if "errors" in response:
                    print(f"⚠️  API returned errors: {response['errors']}")
                    break
                
                # Extract data
                search_result = response.get("data", {}).get("search", {})
                nodes = search_result.get("nodes", [])
                page_info = search_result.get("pageInfo", {})
                
                if not nodes:
                    print("⚠️  No more repositories found")
                    break
                
                # Map to domain models
                for node in nodes:
                    if node and node.get("databaseId"):
                        repo = RepositoryMapper.map_to_repository(node)
                        stats = RepositoryMapper.map_to_statistics(node, crawled_at)
                        
                        self.repositories.append(repo)
                        self.statistics.append(stats)
                
                total_fetched = len(self.repositories)
                print(f"📊 Fetched: {total_fetched}/{self.target_count} repos | "
                      f"Rate limit: {self.client.rate_limit_remaining}")
                
                # Check if we should continue
                if not page_info.get("hasNextPage") or total_fetched >= self.target_count:
                    break
                
                cursor = page_info.get("endCursor")
                
                # Small delay to be respectful
                await asyncio.sleep(0.5)
                
            except Exception as e:
                print(f"❌ Error during crawl: {e}")
                # Continue with what we have
                break
        
        elapsed = time.time() - start_time
        print(f"✅ Crawl completed in {elapsed:.2f} seconds")
        print(f"📈 Total repositories: {len(self.repositories)}")
        
        return self.repositories, self.statistics


async def main():
    """Main entry point"""
    # Get GitHub token from environment
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        raise ValueError("GITHUB_TOKEN environment variable is required")
    
    target_count = int(os.getenv("TARGET_REPO_COUNT", "100000"))
    
    # Initialize and run crawler
    async with GitHubGraphQLClient(github_token) as client:
        crawler = GitHubCrawler(client, target_count)
        repositories, statistics = await crawler.crawl()
        
        # Save to JSON files (will be inserted to DB by separate script)
        with open("repositories.json", "w") as f:
            json.dump(repositories, f, indent=2, default=str)
        
        with open("statistics.json", "w") as f:
            json.dump(statistics, f, indent=2, default=str)
        
        print(f"💾 Saved {len(repositories)} repositories to JSON files")


if __name__ == "__main__":
    asyncio.run(main())