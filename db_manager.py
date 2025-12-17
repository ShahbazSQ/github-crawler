"""
Database Manager - Handles all PostgreSQL operations
Implements efficient batch inserts and upserts
"""

import psycopg2
from psycopg2.extras import execute_batch
from psycopg2 import sql
import json
import os
from typing import List, Dict
from datetime import datetime


class DatabaseManager:
    """Handles all database operations with connection pooling"""
    
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.conn = None
        self.cursor = None
    
    def connect(self):
        """Establish database connection"""
        self.conn = psycopg2.connect(self.connection_string)
        self.cursor = self.conn.cursor()
        print("✅ Connected to PostgreSQL")
    
    def disconnect(self):
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        print("🔌 Disconnected from PostgreSQL")
    
    def setup_schema(self, schema_file: str):
        """Execute schema SQL file (skips if schema already exists)"""
        print("🏗️  Setting up database schema...")
        
        # Check if schema already exists
        self.cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.schemata 
                WHERE schema_name = 'github_data'
            )
        """)
        schema_exists = self.cursor.fetchone()[0]
        
        if schema_exists:
            print("✅ Schema already exists, skipping creation")
            return
        
        with open(schema_file, 'r') as f:
            schema_sql = f.read()
        
        self.cursor.execute(schema_sql)
        self.conn.commit()
        print("✅ Schema created successfully")
    
    def insert_repositories_batch(self, repositories: List[Dict]) -> int:
        """
        Insert repositories using efficient UPSERT (ON CONFLICT)
        Returns: number of rows inserted/updated
        """
        if not repositories:
            return 0
        
        print(f"💾 Inserting {len(repositories)} repositories...")
        
        insert_query = """
            INSERT INTO github_data.repositories 
            (repo_id, full_name, owner_login, repo_name, description, 
             html_url, created_at, is_fork, is_archived, language, 
             last_crawled_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (repo_id) 
            DO UPDATE SET
                full_name = EXCLUDED.full_name,
                owner_login = EXCLUDED.owner_login,
                repo_name = EXCLUDED.repo_name,
                description = EXCLUDED.description,
                html_url = EXCLUDED.html_url,
                is_fork = EXCLUDED.is_fork,
                is_archived = EXCLUDED.is_archived,
                language = EXCLUDED.language,
                last_crawled_at = EXCLUDED.last_crawled_at,
                updated_at = EXCLUDED.updated_at
        """
        
        # Prepare data tuples
        data = [
            (
                repo['repo_id'],
                repo['full_name'],
                repo['owner_login'],
                repo['repo_name'],
                repo.get('description'),
                repo.get('html_url'),
                repo.get('created_at'),
                repo.get('is_fork', False),
                repo.get('is_archived', False),
                repo.get('language'),
                datetime.utcnow(),
                datetime.utcnow()
            )
            for repo in repositories
        ]
        
        # Use execute_batch for better performance
        execute_batch(self.cursor, insert_query, data, page_size=1000)
        self.conn.commit()
        
        print(f"✅ Repositories inserted/updated successfully")
        return len(repositories)
    
    def insert_statistics_batch(self, statistics: List[Dict]) -> int:
        """
        Insert statistics - always INSERT (never update)
        This maintains historical data
        Returns: number of rows inserted
        """
        if not statistics:
            return 0
        
        print(f"📊 Inserting {len(statistics)} statistics records...")
        
        insert_query = """
            INSERT INTO github_data.repo_statistics 
            (repo_id, crawled_at, star_count, fork_count, watcher_count, open_issues_count)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (repo_id, crawled_at) DO NOTHING
        """
        
        # Prepare data tuples
        data = [
            (
                stat['repo_id'],
                stat['crawled_at'],
                stat['star_count'],
                stat['fork_count'],
                stat['watcher_count'],
                stat['open_issues_count']
            )
            for stat in statistics
        ]
        
        # Batch insert
        execute_batch(self.cursor, insert_query, data, page_size=1000)
        self.conn.commit()
        
        print(f"✅ Statistics inserted successfully")
        return len(statistics)
    
    def refresh_materialized_view(self):
        """Refresh the latest stats materialized view"""
        print("🔄 Refreshing materialized view...")
        self.cursor.execute("SELECT github_data.refresh_latest_stats()")
        self.conn.commit()
        print("✅ Materialized view refreshed")
    
    def log_crawl_run(self, repos_crawled: int, repos_failed: int, status: str, error_msg: str = None):
        """Log crawl run metadata"""
        insert_query = """
            INSERT INTO github_data.crawl_runs 
            (started_at, completed_at, repos_crawled, repos_failed, status, error_message)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        
        now = datetime.utcnow()
        self.cursor.execute(insert_query, (now, now, repos_crawled, repos_failed, status, error_msg))
        self.conn.commit()
    
    def export_to_csv(self, output_file: str):
        """Export latest repository stats to CSV"""
        print(f"📤 Exporting data to {output_file}...")
        
        query = """
            COPY (
                SELECT 
                    r.repo_id,
                    r.full_name,
                    r.owner_login,
                    r.repo_name,
                    r.language,
                    s.star_count,
                    s.fork_count,
                    s.watcher_count,
                    s.open_issues_count,
                    s.crawled_at
                FROM github_data.repositories r
                JOIN github_data.latest_repo_stats s ON r.repo_id = s.repo_id
                ORDER BY s.star_count DESC
            ) TO STDOUT WITH CSV HEADER
        """
        
        with open(output_file, 'w') as f:
            self.cursor.copy_expert(query, f)
        
        print(f"✅ Data exported to {output_file}")
    
    def get_stats_summary(self) -> Dict:
        """Get summary statistics about the database"""
        queries = {
            "total_repos": "SELECT COUNT(*) FROM github_data.repositories",
            "total_stats": "SELECT COUNT(*) FROM github_data.repo_statistics",
            "avg_stars": "SELECT AVG(star_count)::INTEGER FROM github_data.latest_repo_stats",
            "max_stars": "SELECT MAX(star_count) FROM github_data.latest_repo_stats",
            "min_stars": "SELECT MIN(star_count) FROM github_data.latest_repo_stats"
        }
        
        results = {}
        for key, query in queries.items():
            self.cursor.execute(query)
            results[key] = self.cursor.fetchone()[0]
        
        return results


def main():
    """Main entry point for database operations"""
    # Database connection from environment
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")
    db_name = os.getenv("POSTGRES_DB", "postgres")
    db_user = os.getenv("POSTGRES_USER", "postgres")
    db_password = os.getenv("POSTGRES_PASSWORD", "postgres")
    
    connection_string = f"host={db_host} port={db_port} dbname={db_name} user={db_user} password={db_password}"
    
    db = DatabaseManager(connection_string)
    
    try:
        db.connect()
        
        # Setup schema if schema.sql exists
        if os.path.exists("schema.sql"):
            db.setup_schema("schema.sql")
        
        # Load and insert data from JSON files
        if os.path.exists("repositories.json"):
            with open("repositories.json", "r") as f:
                repositories = json.load(f)
            db.insert_repositories_batch(repositories)
        
        if os.path.exists("statistics.json"):
            with open("statistics.json", "r") as f:
                statistics = json.load(f)
            db.insert_statistics_batch(statistics)
        
        # Refresh materialized view
        db.refresh_materialized_view()
        
        # Log crawl run
        repos_count = len(repositories) if 'repositories' in locals() else 0
        db.log_crawl_run(repos_count, 0, "completed")
        
        # Export to CSV
        db.export_to_csv("github_repos.csv")
        
        # Print summary
        stats = db.get_stats_summary()
        print("\n📊 Database Summary:")
        print(f"   Total Repositories: {stats['total_repos']:,}")
        print(f"   Total Statistics Records: {stats['total_stats']:,}")
        print(f"   Average Stars: {stats['avg_stars']:,}")
        print(f"   Max Stars: {stats['max_stars']:,}")
        print(f"   Min Stars: {stats['min_stars']:,}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if 'repositories' in locals():
            db.log_crawl_run(0, len(repositories), "failed", str(e))
        raise
    finally:
        db.disconnect()


if __name__ == "__main__":
    main()
