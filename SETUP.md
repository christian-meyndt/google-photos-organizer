# Google Drive Photos Organizer — Setup Guide

## Prerequisites

1. **Python 3.11+**
2. **Ollama** installed and running (`brew install ollama && ollama serve`)
3. **Google Cloud project** with Google Drive API enabled

## Step 1: Install Ollama and the vision model

```bash
brew install ollama
ollama serve  # in a separate terminal
ollama pull llava
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

## Step 7: Choose your workflow

There are two modes depending on where your files live:

### Mode A: Google Drive files (direct)

For files stored directly in Google Drive (uploaded manually, synced from apps):

```bash
# Dry run
photos-organizer run --max-items 50

# Execute (downloads, organizes locally, trashes from Drive)
photos-organizer run --execute

# Images only (skip large videos)
photos-organizer run --execute --images-only
```

### Mode B: Google Photos via Takeout (recommended for phone backups)

For photos/videos that were backed up via Google Photos (the main storage consumer):

1. Go to https://takeout.google.com
2. Click "Deselect all", then select only **Google Photos**
3. Choose delivery method: **Add to Drive**
4. Choose frequency: "Export once" or "Every 2 months"
5. Click "Create export" (may take hours/days for large libraries)
6. Once the export appears in your Drive, run:

```bash
# Dry run — shows what was found
photos-organizer takeout

# Execute — download, organize, trash ZIPs from Drive
photos-organizer takeout --execute

# Images only
photos-organizer takeout --execute --images-only

# Limit items processed
photos-organizer takeout --execute --max-items 500
```

After the tool organizes your files locally, you can safely delete them from Google Photos:
- Go to photos.google.com → Storage → "Review and free up space"

### Check storage

```bash
photos-organizer storage
```

## How it works

### Direct Drive workflow

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
[Classify] Vision model (Ollama/llava):
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

### Takeout workflow

```
Google Drive (Takeout ZIPs)
    │
    ▼
[Find] Locate Takeout ZIP files in Drive
    │
    ▼
[Download & Extract] Download ZIPs, extract media
    │
    ▼
[Assess] Quality check + duplicate detection
    │
    ▼
[Classify] Vision model categorization
    │
    ▼
[Decide] Keep good files, discard bad/duplicates
    │
    ▼
[Organize] Move to: OUTPUT_DIR/YYYY/MM-Month/category/
    │
    ▼
[Trash ZIPs] Remove Takeout ZIPs from Drive
    │
    ▼
[Summary] Report + instructions to delete from Google Photos
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
- **Google Photos API is deprecated** (March 2025) — that's why we use the Takeout approach for phone backups
