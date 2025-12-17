from dotenv import load_dotenv
import os

load_dotenv()
token = os.getenv("GITHUB_TOKEN")
print(f"Token loaded: {token[:10]}..." if token else "Token NOT found!")