"""
================================================================================
GATA GRANTEE SCRAPER - Illinois Grant Data Extraction Tool
================================================================================

WHAT THIS SCRIPT DOES:
    This script extracts all registered grantees and their award data from the
    Illinois GATA (Grant Accountability and Transparency Act) CSFA portal.
    
    Website: https://omb.illinois.gov/public/gata/csfa/GranteeList.aspx

HOW IT WORKS:
    1. Reads a list of grantee IDs from 'grantee_master_list.csv'
    2. For each grantee, visits their page on the GATA website
    3. Selects each fiscal year from the dropdown to get all awards
    4. Saves all award data to 'gata_awards_FINAL.csv'
    
    The script uses 8 parallel browser instances to speed things up.
    A full scrape of ~21,000 grantees takes about 1-2 hours.

BEFORE RUNNING:
    1. Install Python 3.10+ (https://python.org)
    2. Install required packages:
       pip install playwright
    3. Install browser:
       playwright install chromium
    4. Make sure 'grantee_master_list.csv' exists in the same folder

TO RUN:
    python gata_scraper.py
    
RESUME CAPABILITY:
    If the script is interrupted, just run it again - it will resume from
    where it left off. Progress is saved every 30 seconds.

OUTPUT:
    - gata_awards_FINAL.csv: All grantee and award data
    - Columns: Grantee_ID, Grantee_Name, Address, City_State_Zip, Fiscal_Year,
               Award_ID, Program, Agency, Start_Date, End_Date, Amount, 
               Source, Source_URL

Author: Locality Labs
Last Updated: January 2026
================================================================================
"""

# =============================================================================
# IMPORTS - These are Python libraries we need
# =============================================================================
import asyncio          # For running multiple tasks at once (parallel scraping)
import csv              # For reading/writing CSV files
import sys              # For printing to terminal with colors
import time             # For tracking how long things take
import os               # For file/folder operations
from datetime import datetime
from playwright.async_api import async_playwright  # Browser automation library

# =============================================================================
# CONFIGURATION - Change these settings if needed
# =============================================================================

# FILE PATHS
# ----------
# The script automatically finds files in the same folder where it's located.
# You don't need to change these unless you want files in a different location.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # Folder where this script lives
MASTER_LIST = os.path.join(BASE_DIR, 'grantee_master_list.csv')  # Input: list of grantees to scrape
OUTPUT_FILE = os.path.join(BASE_DIR, 'gata_awards_FINAL.csv')    # Output: all scraped data goes here
PROGRESS_FILE = os.path.join(BASE_DIR, 'scrape_progress.txt')    # Tracks progress for resume

# PERFORMANCE SETTINGS
# --------------------
NUM_WORKERS = 8         # How many browser windows to run at once (more = faster but uses more RAM)
                        # Recommended: 4-8 for most computers, reduce to 2-4 if you have <8GB RAM
REQUEST_DELAY = 0.2     # Seconds to wait between requests (be nice to the server)
SAVE_INTERVAL = 100     # Save to CSV every N grantees (lower = safer but slower)

# DATA SOURCE ATTRIBUTION
# -----------------------
# These values are added to every row so you know where the data came from
SOURCE = 'State of Illinois Grant Accountability and Transparency Act'
SOURCE_URL = 'https://gata.illinois.gov/grants/csfa.html'

# OUTPUT COLUMNS
# --------------
# These are the column headers in the output CSV file.
# They use underscores instead of spaces so they work well in SQL databases.
CSV_COLUMNS = [
    'Grantee_ID',       # Unique identifier for the grantee (from URL)
    'Grantee_Name',     # Organization name
    'Grantee_URL',      # Direct link to grantee's page on GATA website
    'Address',          # Street address
    'City_State_Zip',   # City, state and ZIP code
    'Fiscal_Year',      # State fiscal year (e.g., 2025)
    'Award_ID',         # Award identification number (may be blank)
    'Program',          # Grant program name
    'Agency',           # State agency providing the grant
    'Start_Date',       # Award start date
    'End_Date',         # Award end date
    'Amount',           # Dollar amount of the award
    'Source',           # Data source attribution
    'Source_URL'        # Link to GATA portal
]

# =============================================================================
# TERMINAL COLORS - Makes the progress display look nice
# =============================================================================
# These are ANSI escape codes that tell the terminal to display colored text.
# You don't need to understand these - they just make the output prettier.

class Colors:
    """ANSI color codes for terminal output"""
    RESET = '\033[0m'       # Back to default color
    BOLD = '\033[1m'        # Bold text
    DIM = '\033[2m'         # Dimmed/gray text
    
    # Standard colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    # Bright/intense colors
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'


# =============================================================================
# PROGRESS TRACKER - Shows real-time progress in the terminal
# =============================================================================
# This class keeps track of how many grantees we've processed, how many
# awards we've found, estimated time remaining, etc. It displays a nice
# progress bar in the terminal that updates as the scrape runs.
class ProgressTracker:
    """
    Tracks scraping progress and displays a live dashboard in the terminal.
    
    This class is "thread-safe" meaning multiple workers can update it
    simultaneously without causing data corruption (using asyncio.Lock).
    """
    
    def __init__(self, total_grantees, start_index=0):
        """
        Initialize the progress tracker.
        
        Args:
            total_grantees: Total number of grantees to process
            start_index: Where to start (used when resuming an interrupted scrape)
        """
        self.total = total_grantees
        self.processed = start_index          # How many we've done so far
        self.start_index = start_index        # Where we started (for accurate speed calc)
        self.awards_found = 0                 # Running total of awards captured
        self.errors = 0                       # Count of failed grantees
        self.start_time = time.time()         # When we started
        self.current_grantees = [''] * NUM_WORKERS  # What each worker is doing
        self.current_stage = 'Initializing'   # Current phase of the scrape
        self.last_display = 0                 # When we last updated the display
        self.lock = asyncio.Lock()            # Prevents race conditions
        
    async def update(self, worker_id, grantee_name='', awards=0, error=False):
        """
        Called by workers when they finish processing a grantee.
        Updates the counters in a thread-safe way.
        """
        async with self.lock:  # Lock prevents multiple workers updating at once
            self.processed += 1
            self.awards_found += awards
            if error:
                self.errors += 1
            if worker_id < len(self.current_grantees):
                self.current_grantees[worker_id] = grantee_name[:30]  # Truncate long names
        
    def set_stage(self, stage):
        """Update the current stage shown in the progress display."""
        self.current_stage = stage
        
    def get_elapsed(self):
        """Calculate how long the scrape has been running. Returns formatted string."""
        elapsed = time.time() - self.start_time
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)
        if hours > 0:
            return f'{hours}h {minutes:02d}m {seconds:02d}s'
        elif minutes > 0:
            return f'{minutes}m {seconds:02d}s'
        return f'{seconds}s'
    
    def get_eta(self):
        """
        Estimate time remaining based on current processing speed.
        Uses only grantees processed since resume (not total) for accuracy.
        """
        new_processed = self.processed - self.start_index
        if new_processed == 0:
            return 'Calculating...'
        elapsed = time.time() - self.start_time
        rate = new_processed / elapsed  # Grantees per second
        remaining = self.total - self.processed
        eta_seconds = remaining / rate if rate > 0 else 0
        
        hours = int(eta_seconds // 3600)
        minutes = int((eta_seconds % 3600) // 60)
        if hours > 0:
            return f'{hours}h {minutes:02d}m remaining'
        elif minutes > 0:
            return f'{minutes}m remaining'
        return 'Less than 1m'
    
    def get_speed(self):
        """Calculate processing speed in grantees per minute."""
        new_processed = self.processed - self.start_index
        elapsed = time.time() - self.start_time
        if elapsed < 1 or new_processed < 1:
            return '-- /min'
        rate = (new_processed / elapsed) * 60  # Convert to per-minute
        return f'{rate:.1f} /min'
    
    def display(self, force=False):
        """
        Print a nice progress dashboard to the terminal.
        
        This creates a box with progress bar, stats, and ETA.
        It only updates every 0.3 seconds to avoid flickering.
        The '\033[' codes move the cursor up to overwrite the previous display.
        """
        now = time.time()
        if not force and (now - self.last_display) < 0.3:
            return  # Don't update too frequently
        self.last_display = now
        
        c = Colors
        pct = (self.processed / self.total * 100) if self.total > 0 else 0
        
        # Build the progress bar: [========----] style
        bar_width = 40
        filled = int(bar_width * pct / 100)
        bar = c.BRIGHT_GREEN + ('=' * filled) + c.DIM + ('-' * (bar_width - filled)) + c.RESET
        
        # Count active workers (ones currently processing a grantee)
        active = [g for g in self.current_grantees if g]
        workers_display = f'{len(active)}/{NUM_WORKERS} workers'
        
        # Build the display box line by line
        lines = [
            '',
            f'{c.CYAN}+{"="*70}+{c.RESET}',
            f'{c.CYAN}|{c.RESET}  {c.BOLD}{c.BRIGHT_WHITE}GATA GRANTEE SCRAPER{c.RESET}   {c.DIM}[{NUM_WORKERS} parallel]{c.RESET}' + ' ' * 14 + f'{c.YELLOW}[{self.current_stage}]{c.RESET}  {c.CYAN}|{c.RESET}',
            f'{c.CYAN}+{"="*70}+{c.RESET}',
            f'{c.CYAN}|{c.RESET}  Progress: [{bar}] {c.BRIGHT_GREEN}{pct:5.1f}%{c.RESET}   {c.CYAN}|{c.RESET}',
            f'{c.CYAN}|{c.RESET}' + ' ' * 70 + f'{c.CYAN}|{c.RESET}',
            f'{c.CYAN}|{c.RESET}  {c.WHITE}Grantees:{c.RESET}   {c.BRIGHT_CYAN}{self.processed:,}{c.RESET} / {self.total:,}' + ' ' * (70 - 25 - len(f'{self.processed:,}') - len(f'{self.total:,}')) + f'{c.CYAN}|{c.RESET}',
            f'{c.CYAN}|{c.RESET}  {c.WHITE}Awards:{c.RESET}     {c.BRIGHT_CYAN}{self.awards_found:,}{c.RESET} captured' + ' ' * (70 - 23 - len(f'{self.awards_found:,}')) + f'{c.CYAN}|{c.RESET}',
            f'{c.CYAN}|{c.RESET}  {c.WHITE}Errors:{c.RESET}     {c.RED if self.errors > 0 else c.DIM}{self.errors}{c.RESET}' + ' ' * (70 - 15 - len(str(self.errors))) + f'{c.CYAN}|{c.RESET}',
            f'{c.CYAN}|{c.RESET}  {c.WHITE}Workers:{c.RESET}    {c.BRIGHT_YELLOW}{workers_display}{c.RESET}' + ' ' * (70 - 14 - len(workers_display)) + f'{c.CYAN}|{c.RESET}',
            f'{c.CYAN}|{c.RESET}' + ' ' * 70 + f'{c.CYAN}|{c.RESET}',
            f'{c.CYAN}|{c.RESET}  {c.WHITE}Elapsed:{c.RESET}    {c.BRIGHT_WHITE}{self.get_elapsed()}{c.RESET}' + ' ' * (70 - 14 - len(self.get_elapsed())) + f'{c.CYAN}|{c.RESET}',
            f'{c.CYAN}|{c.RESET}  {c.WHITE}ETA:{c.RESET}        {c.BRIGHT_YELLOW}{self.get_eta()}{c.RESET}' + ' ' * (70 - 14 - len(self.get_eta())) + f'{c.CYAN}|{c.RESET}',
            f'{c.CYAN}|{c.RESET}  {c.WHITE}Speed:{c.RESET}      {c.BRIGHT_WHITE}{self.get_speed()}{c.RESET}' + ' ' * (70 - 14 - len(self.get_speed())) + f'{c.CYAN}|{c.RESET}',
            f'{c.CYAN}+{"="*70}+{c.RESET}',
        ]
        
        # Move cursor up to overwrite the previous display (after first few iterations)
        if self.processed > NUM_WORKERS:
            sys.stdout.write(f'\033[{len(lines)}A')
        
        print('\n'.join(lines))
        sys.stdout.flush()


# =============================================================================
# SCRAPING FUNCTIONS - The actual web scraping logic
# =============================================================================
async def scrape_grantee(page, grantee_id, grantee_name):
    """
    Scrape all award data for a single grantee.
    
    IMPORTANT: We use dropdown selection, NOT URL parameters!
    The GATA website ignores fiscal year URL parameters, so we must:
    1. Go to the grantee's page
    2. Find the fiscal year dropdown
    3. Select each year one by one
    4. Extract the awards table for each year
    
    Args:
        page: Playwright browser page object
        grantee_id: The grantee's ID number (from URL)
        grantee_name: The grantee's organization name
        
    Returns:
        List of dictionaries, one per award (or one empty record if no awards)
    """
    results = []
    
    # Step 1: Navigate to the grantee's page
    url = f'https://omb.illinois.gov/public/gata/csfa/Grantee.aspx?id={grantee_id}'
    await page.goto(url, wait_until='networkidle', timeout=60000)
    
    # Step 2: Extract the grantee's address from the page
    # The address is in a div with id="div_Address"
    address = ''
    city_state_zip = ''
    addr_div = await page.query_selector('#div_Address')
    if addr_div:
        addr_text = (await addr_div.inner_text()).strip()
        lines = addr_text.split('\n')
        if len(lines) >= 2:
            address = lines[0].strip()          # First line: street address
            city_state_zip = lines[1].strip()   # Second line: city, state zip
        elif len(lines) == 1:
            city_state_zip = lines[0].strip()
    
    # Step 3: Find the fiscal year dropdown
    # This dropdown has id="ddlFY" and contains all years with awards
    dropdown = await page.query_selector('select#ddlFY')
    if not dropdown:
        # No dropdown means no awards - return empty record for this grantee
        return results
    
    # Step 4: Get all available fiscal years from the dropdown
    options = await dropdown.query_selector_all('option')
    years = [await opt.get_attribute('value') for opt in options]
    
    # Step 5: Process each fiscal year one by one
    # We need to reload the page and select each year because the dropdown
    # triggers a postback that updates the awards table
    for year in years:
        try:
            # Reload the page (needed because selecting a year triggers navigation)
            await page.goto(url, wait_until='networkidle', timeout=60000)
            
            # Select this year from the dropdown
            dropdown = await page.query_selector('select#ddlFY')
            await dropdown.select_option(value=year)
            
            # Wait for the page to update with this year's data
            await page.wait_for_load_state('networkidle')
            await asyncio.sleep(REQUEST_DELAY)  # Be nice to the server
            
            # Step 6: Extract awards from the table
            # The awards table has id="tblList"
            rows = await page.query_selector_all('table#tblList tr')
            
            # Skip the header row (index 0), process data rows
            for row in rows[1:]:
                cells = await row.query_selector_all('td')
                if len(cells) >= 5:
                    # Get the award ID from first column
                    award_id = (await cells[0].inner_text()).strip()
                    
                    # Skip summary rows (they contain "Award count")
                    if 'Award count' in award_id:
                        continue
                    
                    # Build the award record with all fields
                    results.append({
                        'Grantee_ID': grantee_id,
                        'Grantee_Name': grantee_name,
                        'Grantee_URL': url,
                        'Address': address,
                        'City_State_Zip': city_state_zip,
                        'Fiscal_Year': year,
                        'Award_ID': award_id,
                        'Program': (await cells[1].inner_text()).strip(),
                        'Agency': (await cells[2].inner_text()).strip(),
                        'Start_Date': (await cells[3].inner_text()).strip(),
                        'End_Date': (await cells[4].inner_text()).strip(),
                        'Amount': (await cells[5].inner_text()).strip() if len(cells) > 5 else '',
                        'Source': SOURCE,
                        'Source_URL': SOURCE_URL
                    })
        except Exception:
            # If this year fails, skip it and try the next
            # (don't let one bad year stop the whole grantee)
            continue
    
    # Step 7: If no awards found, still record the grantee with empty award fields
    # This ensures we have a record of every grantee, even those with no awards
    if not results:
        results.append({
            'Grantee_ID': grantee_id,
            'Grantee_Name': grantee_name,
            'Grantee_URL': url,
            'Address': address,
            'City_State_Zip': city_state_zip,
            'Fiscal_Year': '',
            'Award_ID': '',
            'Program': '',
            'Agency': '',
            'Start_Date': '',
            'End_Date': '',
            'Amount': '',
            'Source': SOURCE,
            'Source_URL': SOURCE_URL
        })
    
    return results

async def worker(worker_id, queue, results_queue, tracker, browser):
    """
    A worker that processes grantees from the queue.
    
    Multiple workers run in parallel (default: 8). Each worker:
    1. Gets its own browser context (like a separate browser window)
    2. Takes grantees from the queue one at a time
    3. Scrapes their data and puts results in the results queue
    4. Repeats until the queue is empty
    
    Args:
        worker_id: Number identifying this worker (0-7)
        queue: Queue of grantees waiting to be processed
        results_queue: Queue where we put the scraped data
        tracker: Progress tracker for updating the display
        browser: Shared browser instance (workers get their own contexts)
    """
    # Create a new browser context for this worker
    # (Each worker needs its own context to avoid conflicts)
    context = await browser.new_context()
    page = await context.new_page()
    
    # Keep processing grantees until the queue is empty
    while True:
        try:
            # Try to get a grantee from the queue (wait up to 1 second)
            grantee = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            # If queue is empty and we've been waiting, we're done
            if queue.empty():
                break
            continue
        
        try:
            # Scrape this grantee's data
            results = await scrape_grantee(page, grantee['id'], grantee['name'])
            
            # Send results to the writer
            await results_queue.put(results)
            
            # Update progress display
            await tracker.update(worker_id, grantee['name'], len(results))
        except Exception as e:
            # If scraping fails, log the error and continue
            await tracker.update(worker_id, grantee['name'], 0, error=True)
        
        # Refresh the progress display
        tracker.display()
        
        # Mark this task as done
        queue.task_done()
    
    # Clean up when done
    await page.close()
    await context.close()

async def results_writer(results_queue, tracker, first_write, done_event):
    """
    Background task that writes results to the CSV file.
    
    This runs separately from the scrapers so that writing to disk
    doesn't slow down the scraping. It buffers results and writes
    them in batches for efficiency.
    
    Args:
        results_queue: Queue of scraped data waiting to be written
        tracker: Progress tracker to know when we're done
        first_write: True if starting fresh, False if resuming
        done_event: Event that signals when scraping is complete
    """
    buffer = []         # Temporary storage for results
    rows_written = 0    # How many rows we've written so far
    
    while True:
        try:
            # Wait for results from the scrapers (with timeout so we can check done_event)
            results = await asyncio.wait_for(results_queue.get(), timeout=0.5)
            buffer.extend(results)  # Add to buffer
            results_queue.task_done()
            
            # Write to disk when buffer gets big enough
            if len(buffer) >= SAVE_INTERVAL:
                # 'w' = create new file, 'a' = append to existing
                mode = 'w' if first_write and rows_written == 0 else 'a'
                with open(OUTPUT_FILE, mode, newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                    if mode == 'w':
                        writer.writeheader()  # Write column headers first time only
                    writer.writerows(buffer)
                rows_written += len(buffer)
                buffer = []  # Clear the buffer
                
        except asyncio.TimeoutError:
            # Check if scraping is done and queue is empty
            if done_event.is_set() and results_queue.empty():
                break
            continue
    
    # Write any remaining data in the buffer (CRITICAL for small runs!)
    if buffer:
        mode = 'w' if first_write and rows_written == 0 else 'a'
        with open(OUTPUT_FILE, mode, newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            if mode == 'w':
                writer.writeheader()
            writer.writerows(buffer)
        rows_written += len(buffer)
    
    return rows_written

def load_grantee_list():
    """
    Load the list of grantees to scrape from the master CSV file.
    
    The master list should have columns: Grantee_ID, Grantee_Name
    This file is created by scraping the main GATA grantee list page.
    
    Returns:
        List of dictionaries with 'id' and 'name' keys
    """
    grantees = []
    with open(MASTER_LIST, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            grantees.append({
                'id': row['Grantee_ID'],
                'name': row['Grantee_Name']
            })
    return grantees


def load_progress():
    """
    Load the saved progress from a previous run.
    
    This enables the "resume" feature - if the scrape is interrupted,
    we can pick up where we left off instead of starting over.
    
    Returns:
        The index of the last successfully processed grantee (or 0 if none)
    """
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return int(f.read().strip())
    return 0


def save_progress(index):
    """
    Save current progress to disk.
    
    This is called every 30 seconds during scraping so we don't lose
    too much progress if the script is interrupted.
    
    Args:
        index: The index of the last successfully processed grantee
    """
    with open(PROGRESS_FILE, 'w') as f:
        f.write(str(index))

# =============================================================================
# MAIN FUNCTION - This is where everything starts
# =============================================================================

async def main():
    """
    Main entry point for the scraper.
    
    This function:
    1. Loads the list of grantees to scrape
    2. Checks for previous progress (resume capability)
    3. Launches multiple browser workers in parallel
    4. Coordinates scraping and writing to CSV
    5. Displays progress and handles completion
    """
    
    # Enable colored text output on Windows terminals
    os.system('')
    
    # Print welcome banner
    print(f'\n{Colors.BOLD}{Colors.BRIGHT_WHITE}GATA Grantee Scraper - Parallel Mode{Colors.RESET}')
    print(f'{Colors.DIM}{"="*50}{Colors.RESET}\n')
    
    # Load the list of grantees we need to scrape
    grantees = load_grantee_list()
    total = len(grantees)
    print(f'{Colors.CYAN}Loaded {total:,} grantees from master list{Colors.RESET}')
    print(f'{Colors.CYAN}Using {NUM_WORKERS} parallel workers{Colors.RESET}')
    
    # Check if we're resuming from a previous interrupted run
    start_index = load_progress()
    if start_index > 0:
        print(f'{Colors.YELLOW}Resuming from grantee #{start_index + 1}{Colors.RESET}')
        first_write = False  # Append to existing file
        grantees = grantees[start_index:]  # Skip already-processed grantees
    else:
        first_write = True  # Create new file
    
    # Initialize the progress tracker
    tracker = ProgressTracker(total, start_index)
    tracker.set_stage('Scraping')
    
    # Create queues for passing work between tasks
    queue = asyncio.Queue()          # Grantees waiting to be scraped
    results_queue = asyncio.Queue()  # Scraped data waiting to be written
    
    # Create an event to signal when scraping is done
    done_event = asyncio.Event()
    
    # Fill the work queue with all grantees
    for g in grantees:
        await queue.put(g)
    
    # Launch the browser and start scraping
    async with async_playwright() as p:
        # Launch a headless Chrome browser (runs invisibly in background)
        browser = await p.chromium.launch(headless=True)
        
        print(f'{Colors.GREEN}Browser launched. Starting {NUM_WORKERS} workers...{Colors.RESET}\n')
        await asyncio.sleep(1)
        
        # Start the worker tasks (each worker scrapes grantees in parallel)
        workers = [
            asyncio.create_task(worker(i, queue, results_queue, tracker, browser)) 
            for i in range(NUM_WORKERS)
        ]
        
        # Start the writer task (saves results to CSV)
        writer_task = asyncio.create_task(
            results_writer(results_queue, tracker, first_write, done_event)
        )
        
        # Start the progress saver (saves progress every 30 seconds)
        async def progress_saver():
            """Save progress periodically so we can resume if interrupted."""
            while tracker.processed < total:
                save_progress(tracker.processed)
                await asyncio.sleep(30)  # Save every 30 seconds
        
        saver_task = asyncio.create_task(progress_saver())
        
        # Wait for all grantees to be processed
        await queue.join()              # Wait for queue to empty
        await asyncio.gather(*workers)  # Wait for workers to finish
        await results_queue.join()      # Wait for results to be queued
        
        # Signal writer that scraping is done, then wait for it to finish
        done_event.set()
        await writer_task  # Wait for writer to flush final buffer
        
        # Cancel the progress saver (we're done)
        saver_task.cancel()
        
        # Close the browser
        await browser.close()
    
    # Final display update
    tracker.set_stage('Complete')
    tracker.display(force=True)
    save_progress(total)
    
    # Print completion summary
    print(f'\n{Colors.BRIGHT_GREEN}Scrape complete!{Colors.RESET}')
    print(f'{Colors.WHITE}Output: {OUTPUT_FILE}{Colors.RESET}')
    print(f'{Colors.WHITE}Total awards: {tracker.awards_found:,}{Colors.RESET}')
    print(f'{Colors.WHITE}Total time: {tracker.get_elapsed()}{Colors.RESET}')
    
    # Clean up progress file (we're done, don't need to resume)
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)


# =============================================================================
# SCRIPT ENTRY POINT
# =============================================================================
# This runs when you execute: python gata_scraper.py

if __name__ == '__main__':
    asyncio.run(main())
