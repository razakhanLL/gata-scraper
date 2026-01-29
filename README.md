# Illinois GATA Grantee Scraper

Scrapes all registered grantees and their award data from the Illinois Grant Accountability and Transparency Act (GATA) CSFA website.

## Data Source

- **Website:** https://gata.illinois.gov/grants/csfa.html
- **Data Portal:** https://omb.illinois.gov/public/gata/csfa/GranteeList.aspx
- **Source:** State of Illinois Grant Accountability and Transparency Act

## Data Summary

| Metric | Value |
|--------|-------|
| Total award records | 293,631 |
| Unique grantees | 21,326 |
| Fiscal years covered | 2005-2049 |
| Scrape date | January 28, 2026 |

## Output File

**`gata_awards_FINAL.csv`** - Complete dataset with all grantees and their awards

### Column Definitions

| Column | Description | Example |
|--------|-------------|---------|
| Grantee_ID | Unique identifier for the grantee | 697159 |
| Grantee_Name | Organization name | Northern Illinois Center for Nonprofit Excellence |
| Grantee_URL | Direct link to grantee page | https://omb.illinois.gov/public/gata/csfa/Grantee.aspx?id=697159 |
| Address | Street address | 123 Main St |
| City_State_Zip | City, state and ZIP code | Springfield, IL 62701 |
| Fiscal_Year | State fiscal year of the award | 2025 |
| Award_ID | Award identification number (may be empty) | 22-611040 |
| Program | Grant program name | Illinois Travel and Tourism Grant Program |
| Agency | Granting state agency | DCEO (420) |
| Start_Date | Award start date | 01-01-2023 |
| End_Date | Award end date | 06-30-2024 |
| Amount | Award amount in dollars | 99,428 |
| Source | Data source attribution | State of Illinois Grant Accountability and Transparency Act |
| Source_URL | Link to GATA portal | https://gata.illinois.gov/grants/csfa.html |

## Requirements

- Python 3.13+
- Playwright (`pip install playwright`)
- Chromium browser (`playwright install chromium`)

## Usage

### Run the scraper

```bash
python gata_scraper.py
```

The scraper:
- Uses 8 parallel browser instances for speed
- Saves progress every 30 seconds (resume-capable)
- Completes in approximately 1-2 hours
- Outputs to `gata_awards_FINAL.csv`

### Resume after interruption

Simply run the script again - it will automatically resume from where it left off.

### Reset and start fresh

Delete `scrape_progress.txt` and `gata_awards_FINAL.csv`, then run the scraper.

## Technical Notes

- The scraper uses dropdown selection (not URL parameters) to accurately capture awards per fiscal year
- Each grantee has dynamic fiscal years available (not a fixed range)
- Some awards have empty Award_ID fields - these are intentionally captured
- Parallel scraping uses separate browser contexts to avoid state conflicts

## License

This project scrapes publicly available government data. Use responsibly and in accordance with applicable terms of service.
