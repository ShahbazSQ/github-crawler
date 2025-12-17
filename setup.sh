#!/bin/bash

# GitHub Crawler Setup Script
# Makes it easy to test locally before pushing to GitHub

set -e  # Exit on error

echo "=================================="
echo "GitHub Crawler - Local Setup"
echo "=================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if PostgreSQL is installed
echo -e "\n${YELLOW}Checking PostgreSQL...${NC}"
if ! command -v psql &> /dev/null; then
    echo -e "${RED}PostgreSQL is not installed!${NC}"
    echo "Install it with:"
    echo "  macOS:   brew install postgresql"
    echo "  Ubuntu:  sudo apt-get install postgresql"
    exit 1
fi
echo -e "${GREEN}✓ PostgreSQL found${NC}"

# Check if Python 3.11+ is installed
echo -e "\n${YELLOW}Checking Python...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Python 3 is not installed!${NC}"
    exit 1
fi
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo -e "${GREEN}✓ Python $PYTHON_VERSION found${NC}"

# Create virtual environment
echo -e "\n${YELLOW}Creating virtual environment...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}✓ Virtual environment created${NC}"
else
    echo -e "${GREEN}✓ Virtual environment already exists${NC}"
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo -e "\n${YELLOW}Installing Python dependencies...${NC}"
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo -e "${GREEN}✓ Dependencies installed${NC}"

# Setup PostgreSQL database
echo -e "\n${YELLOW}Setting up PostgreSQL database...${NC}"
DB_NAME="github_crawler_test"

# Create database if it doesn't exist
if psql -lqt | cut -d \| -f 1 | grep -qw $DB_NAME; then
    echo -e "${GREEN}✓ Database '$DB_NAME' already exists${NC}"
else
    createdb $DB_NAME
    echo -e "${GREEN}✓ Database '$DB_NAME' created${NC}"
fi

# Run schema
echo -e "\n${YELLOW}Creating database schema...${NC}"
psql -d $DB_NAME -f schema.sql -q
echo -e "${GREEN}✓ Schema created successfully${NC}"

# Create .env file
echo -e "\n${YELLOW}Creating .env file...${NC}"
if [ ! -f ".env" ]; then
    cat > .env << EOF
# GitHub Token (required)
GITHUB_TOKEN=your_github_token_here

# Database connection
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=$DB_NAME
POSTGRES_USER=$USER
POSTGRES_PASSWORD=

# Crawler settings
TARGET_REPO_COUNT=1000
EOF
    echo -e "${GREEN}✓ .env file created${NC}"
    echo -e "${YELLOW}⚠️  Please edit .env and add your GitHub token!${NC}"
else
    echo -e "${GREEN}✓ .env file already exists${NC}"
fi

# Print next steps
echo -e "\n${GREEN}=================================="
echo "Setup Complete! 🎉"
echo "==================================${NC}"
echo ""
echo "Next steps:"
echo ""
echo "1. Edit .env file and add your GitHub token:"
echo "   ${YELLOW}nano .env${NC}"
echo ""
echo "2. Get a GitHub token from:"
echo "   ${YELLOW}https://github.com/settings/tokens${NC}"
echo "   (No special permissions needed - just read:public access)"
echo ""
echo "3. Run the crawler:"
echo "   ${YELLOW}python crawler.py${NC}"
echo ""
echo "4. Insert data into database:"
echo "   ${YELLOW}python db_manager.py${NC}"
echo ""
echo "5. Query the database:"
echo "   ${YELLOW}psql -d $DB_NAME${NC}"
echo ""
echo "Example queries:"
echo "   ${YELLOW}SELECT full_name, star_count FROM github_data.repositories r"
echo "   JOIN github_data.latest_repo_stats s ON r.repo_id = s.repo_id"
echo "   ORDER BY star_count DESC LIMIT 10;${NC}"
echo ""
echo "=================================="