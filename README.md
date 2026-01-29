# Illinois GATA Grantee Scraper 🏛️

> **What does this do?** This tool automatically downloads all grant award data from the Illinois GATA (Grant Accountability and Transparency Act) website and saves it to a spreadsheet you can open in Excel.

---

## 📋 Table of Contents

1. [What is GATA?](#what-is-gata)
2. [What Data Does This Collect?](#what-data-does-this-collect)
3. [Quick Start Guide](#quick-start-guide)
4. [Choose Your Version](#choose-your-version)
   - [Python Version](#python-version-recommended)
   - [Ruby Version](#ruby-version-alternative)
5. [Understanding the Output](#understanding-the-output)
6. [Common Tasks](#common-tasks)
7. [Troubleshooting](#troubleshooting)
8. [Technical Details](#technical-details)

---

## What is GATA?

The **Grant Accountability and Transparency Act (GATA)** is an Illinois state law requiring all grant-making agencies to publish information about their grants. This includes:

- Who received grants (grantees)
- How much money was awarded
- Which programs funded the grants
- When the grant periods started and ended

**Official Website:** https://gata.illinois.gov/grants/csfa.html

---

## What Data Does This Collect?

| Metric | Value |
|--------|-------|
| 📊 Total award records | 293,631 |
| 🏢 Unique grantees | 21,326 |
| 📅 Fiscal years covered | 2005-2049 |
| 🕐 Last full scrape | January 28, 2026 |

---

## Quick Start Guide

### Step 1: Download this project

```bash
git clone https://github.com/razakhanLL/gata-scraper.git
cd gata-scraper
```

Or download the ZIP file from GitHub and extract it.

### Step 2: Choose Python or Ruby (see below)

### Step 3: Run the scraper

### Step 4: Open `gata_awards_FINAL.csv` in Excel

---

## Choose Your Version

We provide **two versions** of the scraper. Pick the one that matches your setup:

| Feature | Python Version | Ruby Version |
|---------|----------------|--------------|
| Speed | ⚡ Faster (~1-2 hours) | 🐢 Slower (~2-3 hours) |
| Setup | Moderate | Moderate |
| Browser Engine | Playwright (Chromium) | Selenium (Chrome) |
| Recommended? | ✅ Yes | For Ruby developers |

---

## Python Version (Recommended)

### Prerequisites

Before running, you need:

1. **Python 3.10 or higher** - [Download here](https://www.python.org/downloads/)
2. **Playwright library** - Automates the web browser

### Installation (One-Time Setup)

Open a terminal (Command Prompt on Windows, Terminal on Mac) and run:

```bash
# Step 1: Install the Playwright library
pip install playwright

# Step 2: Install the Chromium browser (used by Playwright)
playwright install chromium
```

**What do these commands do?**
- `pip install playwright` - Downloads the Playwright package that controls web browsers
- `playwright install chromium` - Downloads a special version of Chrome for automation

### Running the Scraper

```bash
# Navigate to the project folder
cd "path/to/gata-scraper"

# Run the scraper
python gata_scraper.py
```

### What You'll See

```
+======================================================================+
|  GATA SCRAPER [8 workers]                   [Scraping]               |
+======================================================================+
|  Progress: [====================--------------------]  50.0%         |
|  Grantees: 10,000 / 21,326                                           |
|  Awards:   140,000  |  Errors: 0                                     |
|  Elapsed:  45m 30s  |  ETA: 45m  |  Speed: 220/min                   |
+======================================================================+
```

**What does this mean?**
- **Progress bar** - Visual indicator of completion
- **Grantees** - How many organizations have been processed
- **Awards** - Total grant records collected so far
- **Errors** - Number of failed attempts (should be 0)
- **ETA** - Estimated time remaining

---

## Ruby Version (Alternative)

### Prerequisites

Before running, you need:

1. **Ruby 3.0 or higher** - [Download here](https://rubyinstaller.org/) (Windows) or use `brew install ruby` (Mac)
2. **Google Chrome browser** - [Download here](https://www.google.com/chrome/)
3. **Bundler** - Ruby's package manager

### Installation (One-Time Setup)

Open a terminal and run:

```bash
# Step 1: Navigate to the project folder
cd "path/to/gata-scraper"

# Step 2: Install Bundler (if not already installed)
gem install bundler

# Step 3: Install required gems (libraries)
bundle install
```

**What do these commands do?**
- `gem install bundler` - Installs Ruby's package manager
- `bundle install` - Reads the `Gemfile` and installs all required libraries

### Running the Scraper

```bash
# Make sure you're in the project folder
cd "path/to/gata-scraper"

# Run the scraper
ruby gata_scraper.rb
```

---

## Understanding the Output

The scraper creates a file called **`gata_awards_FINAL.csv`** that you can open in Excel.

### Column Definitions

| Column | What It Means | Example |
|--------|---------------|---------|
| `Grantee_ID` | Unique ID number for the organization | `697159` |
| `Grantee_Name` | Name of the organization that received the grant | `Northern Illinois Center for Nonprofit Excellence` |
| `Grantee_URL` | Link to view this grantee on the GATA website | `https://omb.illinois.gov/public/gata/csfa/Grantee.aspx?id=697159` |
| `Address` | Street address (may be empty) | `123 Main St` |
| `City_State_Zip` | City, state, and ZIP code (may be empty) | `Springfield, IL 62701` |
| `Fiscal_Year` | Illinois state fiscal year (July 1 - June 30) | `2025` |
| `Award_ID` | Grant award identification number | `22-611040` |
| `Program` | Name of the grant program | `Illinois Travel and Tourism Grant Program` |
| `Agency` | State agency that gave the grant | `DCEO (420)` |
| `Start_Date` | When the grant period started | `01-01-2023` |
| `End_Date` | When the grant period ended | `06-30-2024` |
| `Amount` | Dollar amount of the grant | `99,428` |
| `Source` | Where this data came from | `State of Illinois Grant Accountability and Transparency Act` |
| `Source_URL` | Link to the GATA website | `https://gata.illinois.gov/grants/csfa.html` |

### Sample Data

```
Grantee_ID,Grantee_Name,Grantee_URL,Fiscal_Year,Award_ID,Program,Agency,Amount
686134,Galapagos Rockford Charter School,https://...,2017,103949,National School Lunch Program,ISBE (586),"69,540"
```

---

## Common Tasks

### 🔄 Resume After Interruption

If the scraper stops (computer restart, network issue, etc.), just run it again:

```bash
python gata_scraper.py   # or: ruby gata_scraper.rb
```

It will **automatically continue** from where it left off. Progress is saved every 30 seconds.

### 🗑️ Start Fresh (Delete All Progress)

If you want to start over from scratch:

**Windows (PowerShell):**
```powershell
Remove-Item scrape_progress.txt -ErrorAction SilentlyContinue
Remove-Item gata_awards_FINAL.csv -ErrorAction SilentlyContinue
```

**Mac/Linux (Terminal):**
```bash
rm -f scrape_progress.txt gata_awards_FINAL.csv
```

Then run the scraper again.

### 📊 Open Results in Excel

1. Navigate to the project folder
2. Double-click `gata_awards_FINAL.csv`
3. Excel will open it automatically

**Tip:** To filter by a specific grantee, use Excel's Filter feature (Data → Filter)

---

## Troubleshooting

### ❌ "playwright not found" or "No module named playwright"

You need to install Playwright first:
```bash
pip install playwright
playwright install chromium
```

### ❌ "ruby: command not found"

Ruby isn't installed. Download it from https://rubyinstaller.org/ (Windows) or run `brew install ruby` (Mac).

### ❌ "chromedriver not found" (Ruby version)

The Selenium library should auto-download ChromeDriver, but if it doesn't:
1. Make sure Google Chrome is installed
2. Try: `gem install webdrivers`

### ❌ Scraper is very slow

This is normal! The scraper must:
1. Open each grantee's page
2. Click through every fiscal year
3. Wait for the page to load each time

A full scrape of 21,000+ grantees takes 1-2 hours with 8 parallel browsers.

### ❌ "Connection refused" or network errors

The GATA website may be temporarily down. Wait a few minutes and try again.

### ❌ Progress shows 0 awards for most grantees

This is normal! Most grantees have no awards in the system - they're just registered.

---

## Technical Details

### How the Scraper Works

```
┌─────────────────────────────────────────────────────────────────────┐
│                        GATA Website                                  │
│  https://omb.illinois.gov/public/gata/csfa/GranteeList.aspx         │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  1. Load grantee_master_list.csv (21,326 grantees)                  │
│  2. Launch 8 browser instances in parallel                          │
│  3. For each grantee:                                               │
│     a. Go to their page: Grantee.aspx?id={ID}                       │
│     b. Find all available fiscal years in the dropdown              │
│     c. For each fiscal year:                                        │
│        - Select the year (triggers page reload)                     │
│        - Read all awards from the table                             │
│        - Save to results queue                                      │
│  4. Write results to CSV file                                       │
│  5. Save progress every 30 seconds                                  │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    gata_awards_FINAL.csv                            │
│                    (293,631 award records)                          │
└─────────────────────────────────────────────────────────────────────┘
```

### Why 8 Workers?

We use 8 parallel browser instances because:
- More browsers = faster scraping (8x speedup vs 1 browser)
- More than 8 doesn't help much (website rate limits, CPU limits)
- Each browser has its own session so they don't interfere

### Files in This Project

| File | Purpose |
|------|---------|
| `gata_scraper.py` | Python version of the scraper |
| `gata_scraper.rb` | Ruby version of the scraper |
| `Gemfile` | Ruby dependencies (for `bundle install`) |
| `grantee_master_list.csv` | Input: List of all 21,326 grantees to scrape |
| `gata_awards_FINAL.csv` | Output: All collected award data |
| `scrape_progress.txt` | Tracks which grantees have been processed |
| `README.md` | This file! |

### Data Source

- **Website:** https://gata.illinois.gov/grants/csfa.html
- **Data Portal:** https://omb.illinois.gov/public/gata/csfa/GranteeList.aspx
- **Legal:** This is publicly available government data

---

## 📄 License

This project scrapes publicly available government data. Use responsibly and in accordance with applicable terms of service.

---

## 🤝 Contributing

Found a bug? Have an idea? Open an issue or pull request on GitHub!

---

Made with ❤️ for Illinois government transparency
