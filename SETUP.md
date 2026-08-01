# Google Drive Photos Organizer — Setup Guide

## Prerequisites

1. **Python 3.11+**
2. **Ollama** installed and running (`brew install ollama && ollama serve`)
3. **Google Cloud project** with Google Drive API enabled

## Step 1: Install Ollama and the vision model

```bash
brew install ollama
ollama serve  # in a separate terminal
ollama pull llama3.2-vision
```

## Step 2: Set up Google Cloud credentials

1. Go to https://console.cloud.google.com/
2. Create a new project (or select existing)
3. Enable the **Google Drive API** (APIs & Dienste → Bibliothek → search "Google Drive API")
4. Set up the **OAuth consent screen** (External, add your email as test user, add scope `https://www.googleapis.com/auth/drive`)
5. Go to **Credentials** → Create **OAuth 2.0 Client ID** (Desktop app type)
6. Download the JSON file and save it as `credentials.json` in the project root

**Important:** Add both your and your wife's Google accounts as test users under
**OAuth consent screen** → **Test users** (required while app is in testing mode).

## Step 3: Install the project

```bash
cd "AI Projects/google-photos-organizer"
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Step 4: Configure

```bash
cp .env.example .env
# Edit .env with your preferences (output dir, etc.)
```

## Step 5: Authenticate both accounts

```bash
photos-organizer auth christian
photos-organizer auth wife
```

Each command opens a browser for Google sign-in. Tokens are saved locally.

## Step 6: Check everything is ready

```bash
photos-organizer status
```

## Step 7: Run (dry run first!)

```bash
# Dry run — shows what would happen without changing anything
photos-organizer run

# Process more items
photos-organizer run --max-items 500

# Actually execute (downloads, organizes locally, trashes from Drive)
photos-organizer run --execute

# Check storage usage
photos-organizer storage
```

## How it works

```
Google Drive (2 accounts)
    │
    ▼
[Fetch] List media files, sorted by size (largest first)
    │
    ▼
[Download & Assess] For each item:
    ├── Compute perceptual hash (dedup)
    ├── Measure blur (quality)
    └── Check resolution
    │
    ▼
[Classify] Vision model (Ollama/llama3.2-vision):
    ├── Assign category (family, travel, food, etc.)
    └── Generate description
    │
    ▼
[Decide]
    ├── Bad quality / duplicates → discard (not saved locally)
    └── Good files → organize locally
    │
    ▼
[Organize] Move to: OUTPUT_DIR/YYYY/MM-Month/category/
    │
    ▼
[Summarize folders] Generate README.txt per folder
    │
    ▼
[Trash from Drive] All processed files trashed to free space
```

## Folder structure output

```
~/Pictures/Organized/
├── 2024/
│   ├── 01-January/
│   │   ├── family/
│   │   │   ├── IMG_1234.jpg
│   │   │   └── README.txt
│   │   └── travel/
│   │       ├── IMG_5678.jpg
│   │       └── README.txt
│   └── 02-February/
│       └── ...
└── 2025/
    └── ...
```

## Notes

- **Dry run by default** — nothing is modified unless you pass `--execute`
- **Deletion is trash, not permanent** — you have 30 days to recover trashed files in Google Drive
- **All processed files are removed from Drive** — good files are saved locally first, bad quality / duplicates are just trashed
- **Files are processed largest first** — so you free the most space quickly
- **Videos** are downloaded and organized by date, but not classified by vision model
- **Perceptual hashing** catches near-duplicates (crops, resizes, slight edits)
- The vision model runs **locally** via Ollama — no API costs, no data leaves your machine
