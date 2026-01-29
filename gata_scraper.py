"""
GATA Grantee Scraper - Production Version (Parallel)
Scrapes Illinois GATA CSFA registered grantees and their awards
Uses parallel workers for efficiency, dropdown selection for accuracy
"""
import asyncio
import csv
import sys
import time
import os
from datetime import datetime
from playwright.async_api import async_playwright

# =============================================================================
# CONFIGURATION
# =============================================================================
BASE_DIR = 'C:/Users/rkhan/Documents/Gata Scrape'
MASTER_LIST = f'{BASE_DIR}/grantee_master_list.csv'
OUTPUT_FILE = f'{BASE_DIR}/gata_awards_FINAL.csv'
PROGRESS_FILE = f'{BASE_DIR}/scrape_progress.txt'

# Parallel settings
NUM_WORKERS = 8  # Number of concurrent browser contexts
REQUEST_DELAY = 0.2  # Delay between requests per worker (seconds)

# Save settings
SAVE_INTERVAL = 100  # Write to CSV every N grantees

# Source attribution
SOURCE = 'State of Illinois Grant Accountability and Transparency Act'
SOURCE_URL = 'https://gata.illinois.gov/grants/csfa.html'

# SQL-friendly column names
CSV_COLUMNS = [
    'Grantee_ID', 'Grantee_Name', 'Address', 'City_State_Zip',
    'Fiscal_Year', 'Award_ID', 'Program', 'Agency', 
    'Start_Date', 'End_Date', 'Amount', 'Source', 'Source_URL'
]

# =============================================================================
# ANSI COLOR CODES
# =============================================================================
class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'

# =============================================================================
# PROGRESS TRACKER (Thread-safe)
# =============================================================================
class ProgressTracker:
    def __init__(self, total_grantees, start_index=0):
        self.total = total_grantees
        self.processed = start_index
        self.start_index = start_index  # Track where we resumed from
        self.awards_found = 0
        self.errors = 0
        self.start_time = time.time()
        self.current_grantees = [''] * NUM_WORKERS
        self.current_stage = 'Initializing'
        self.last_display = 0
        self.lock = asyncio.Lock()
        
    async def update(self, worker_id, grantee_name='', awards=0, error=False):
        async with self.lock:
            self.processed += 1
            self.awards_found += awards
            if error:
                self.errors += 1
            if worker_id < len(self.current_grantees):
                self.current_grantees[worker_id] = grantee_name[:30]
        
    def set_stage(self, stage):
        self.current_stage = stage
        
    def get_elapsed(self):
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
        # Use only NEW grantees processed since resume for speed calculation
        new_processed = self.processed - self.start_index
        if new_processed == 0:
            return 'Calculating...'
        elapsed = time.time() - self.start_time
        rate = new_processed / elapsed
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
        # Use only NEW grantees processed since resume
        new_processed = self.processed - self.start_index
        elapsed = time.time() - self.start_time
        if elapsed < 1 or new_processed < 1:
            return '-- /min'
        rate = (new_processed / elapsed) * 60
        return f'{rate:.1f} /min'
    
    def display(self, force=False):
        now = time.time()
        if not force and (now - self.last_display) < 0.3:
            return
        self.last_display = now
        
        c = Colors
        pct = (self.processed / self.total * 100) if self.total > 0 else 0
        
        bar_width = 40
        filled = int(bar_width * pct / 100)
        bar = c.BRIGHT_GREEN + ('=' * filled) + c.DIM + ('-' * (bar_width - filled)) + c.RESET
        
        # Show active workers
        active = [g for g in self.current_grantees if g]
        workers_display = f'{len(active)}/{NUM_WORKERS} workers'
        
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
        
        if self.processed > NUM_WORKERS:
            sys.stdout.write(f'\033[{len(lines)}A')
        
        print('\n'.join(lines))
        sys.stdout.flush()

# =============================================================================
# SCRAPING FUNCTIONS
# =============================================================================
async def scrape_grantee(page, grantee_id, grantee_name):
    """Scrape a single grantee using correct dropdown approach"""
    results = []
    
    url = f'https://omb.illinois.gov/public/gata/csfa/Grantee.aspx?id={grantee_id}'
    await page.goto(url, wait_until='networkidle', timeout=60000)
    
    # Get grantee info
    address = ''
    city_state_zip = ''
    addr_div = await page.query_selector('#div_Address')
    if addr_div:
        addr_text = (await addr_div.inner_text()).strip()
        lines = addr_text.split('\n')
        if len(lines) >= 2:
            address = lines[0].strip()
            city_state_zip = lines[1].strip()
        elif len(lines) == 1:
            city_state_zip = lines[0].strip()
    
    # Get available fiscal years
    dropdown = await page.query_selector('select#ddlFY')
    if not dropdown:
        return results
    
    options = await dropdown.query_selector_all('option')
    years = [await opt.get_attribute('value') for opt in options]
    
    # Process each fiscal year
    for year in years:
        try:
            await page.goto(url, wait_until='networkidle', timeout=60000)
            dropdown = await page.query_selector('select#ddlFY')
            await dropdown.select_option(value=year)
            await page.wait_for_load_state('networkidle')
            await asyncio.sleep(REQUEST_DELAY)
            
            rows = await page.query_selector_all('table#tblList tr')
            
            for row in rows[1:]:
                cells = await row.query_selector_all('td')
                if len(cells) >= 5:
                    award_id = (await cells[0].inner_text()).strip()
                    if 'Award count' in award_id:
                        continue
                    
                    results.append({
                        'Grantee_ID': grantee_id,
                        'Grantee_Name': grantee_name,
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
            continue
    
    # If no awards, still record grantee
    if not results:
        results.append({
            'Grantee_ID': grantee_id,
            'Grantee_Name': grantee_name,
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
    """Worker that processes grantees from queue - each worker gets its own context"""
    context = await browser.new_context()
    page = await context.new_page()
    
    while True:
        try:
            grantee = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            if queue.empty():
                break
            continue
        
        try:
            results = await scrape_grantee(page, grantee['id'], grantee['name'])
            await results_queue.put(results)
            await tracker.update(worker_id, grantee['name'], len(results))
        except Exception as e:
            await tracker.update(worker_id, grantee['name'], 0, error=True)
        
        tracker.display()
        queue.task_done()
    
    await page.close()
    await context.close()

async def results_writer(results_queue, tracker, first_write):
    """Writer that saves results to CSV"""
    buffer = []
    rows_written = 0
    
    while True:
        try:
            results = await asyncio.wait_for(results_queue.get(), timeout=2.0)
            buffer.extend(results)
            results_queue.task_done()
            
            # Periodic save
            if len(buffer) >= SAVE_INTERVAL:
                mode = 'w' if first_write and rows_written == 0 else 'a'
                with open(OUTPUT_FILE, mode, newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                    if mode == 'w':
                        writer.writeheader()
                    writer.writerows(buffer)
                rows_written += len(buffer)
                buffer = []
                
        except asyncio.TimeoutError:
            if results_queue.empty() and tracker.processed >= tracker.total:
                break
            continue
    
    # Final save
    if buffer:
        mode = 'w' if first_write and rows_written == 0 else 'a'
        with open(OUTPUT_FILE, mode, newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            if mode == 'w':
                writer.writeheader()
            writer.writerows(buffer)

def load_grantee_list():
    """Load grantee master list"""
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
    """Load progress from file"""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return int(f.read().strip())
    return 0

def save_progress(index):
    """Save progress to file"""
    with open(PROGRESS_FILE, 'w') as f:
        f.write(str(index))

# =============================================================================
# MAIN
# =============================================================================
async def main():
    os.system('')  # Enable Windows ANSI
    
    print(f'\n{Colors.BOLD}{Colors.BRIGHT_WHITE}GATA Grantee Scraper - Parallel Mode{Colors.RESET}')
    print(f'{Colors.DIM}{"="*50}{Colors.RESET}\n')
    
    # Load grantee list
    grantees = load_grantee_list()
    total = len(grantees)
    print(f'{Colors.CYAN}Loaded {total:,} grantees from master list{Colors.RESET}')
    print(f'{Colors.CYAN}Using {NUM_WORKERS} parallel workers{Colors.RESET}')
    
    # Check for resume
    start_index = load_progress()
    if start_index > 0:
        print(f'{Colors.YELLOW}Resuming from grantee #{start_index + 1}{Colors.RESET}')
        first_write = False
        grantees = grantees[start_index:]
    else:
        first_write = True
    
    # Initialize tracker with start_index for accurate speed/ETA
    tracker = ProgressTracker(total, start_index)
    tracker.set_stage('Scraping')
    
    queue = asyncio.Queue()
    results_queue = asyncio.Queue()
    
    # Fill queue
    for g in grantees:
        await queue.put(g)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        print(f'{Colors.GREEN}Browser launched. Starting {NUM_WORKERS} workers...{Colors.RESET}\n')
        await asyncio.sleep(1)
        
        # Start workers and writer - pass browser instead of context
        workers = [asyncio.create_task(worker(i, queue, results_queue, tracker, browser)) 
                   for i in range(NUM_WORKERS)]
        writer_task = asyncio.create_task(results_writer(results_queue, tracker, first_write))
        
        # Progress saver
        async def progress_saver():
            while tracker.processed < total:
                save_progress(tracker.processed)
                await asyncio.sleep(30)
        
        saver_task = asyncio.create_task(progress_saver())
        
        # Wait for completion
        await queue.join()
        await asyncio.gather(*workers)
        await results_queue.join()
        
        saver_task.cancel()
        await browser.close()
    
    # Final
    tracker.set_stage('Complete')
    tracker.display(force=True)
    save_progress(total)
    
    print(f'\n{Colors.BRIGHT_GREEN}Scrape complete!{Colors.RESET}')
    print(f'{Colors.WHITE}Output: {OUTPUT_FILE}{Colors.RESET}')
    print(f'{Colors.WHITE}Total awards: {tracker.awards_found:,}{Colors.RESET}')
    print(f'{Colors.WHITE}Total time: {tracker.get_elapsed()}{Colors.RESET}')
    
    # Clean up progress file
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)

if __name__ == '__main__':
    asyncio.run(main())
