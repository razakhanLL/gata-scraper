# ==============================================================================
# GATA GRANTEE SCRAPER - Illinois Grant Data Extraction Tool (Ruby Version)
# ==============================================================================
#
# WHAT THIS SCRIPT DOES:
#     This script extracts all registered grantees and their award data from the
#     Illinois GATA (Grant Accountability and Transparency Act) CSFA portal.
#
#     Website: https://omb.illinois.gov/public/gata/csfa/GranteeList.aspx
#
# HOW IT WORKS:
#     1. Reads a list of grantee IDs from 'grantee_master_list.csv'
#     2. For each grantee, visits their page on the GATA website
#     3. Loads each fiscal year via URL parameters to get all awards
#     4. Saves all award data to 'gata_awards_FINAL.csv'
#
#     The script uses 8 parallel browser instances to speed things up.
#     A full scrape of ~21,000 grantees takes about 2-3 hours.
#
# BEFORE RUNNING:
#     1. Install Ruby 3.0+ (https://rubyinstaller.org for Windows)
#     2. Install required gems:
#        gem install selenium-webdriver concurrent-ruby
#     3. Make sure Chrome/Chromium browser is installed
#     4. Make sure 'grantee_master_list.csv' exists in the same folder
#
# TO RUN:
#     ruby gata_scraper.rb
#
# RESUME CAPABILITY:
#     If the script is interrupted, just run it again - it will resume from
#     where it left off. Progress is saved every 30 seconds.
#
# OUTPUT:
#     - gata_awards_FINAL.csv: All grantee and award data
#     - Columns: Grantee_ID, Grantee_Name, Grantee_URL, Address, City_State_Zip,
#                Fiscal_Year, Award_ID, Program, Agency, Start_Date, End_Date,
#                Amount, Source, Source_URL
#
# PYTHON VS RUBY:
#     This is a Ruby port of the Python scraper. Key differences:
#     - Uses Selenium WebDriver instead of Playwright
#     - Uses Ruby threads instead of Python asyncio
#     - Slightly slower due to Selenium overhead (~2-3 hours vs ~1-2 hours)
#
# Author: Locality Labs
# Last Updated: January 2026
# ==============================================================================

# =============================================================================
# IMPORTS - These are Ruby libraries (gems) we need
# =============================================================================

require 'selenium-webdriver'  # Browser automation (controls Chrome)
require 'csv'                 # For reading/writing CSV files
require 'concurrent'          # For thread-safe data structures

# =============================================================================
# CONFIGURATION - Change these settings if needed
# =============================================================================

# PERFORMANCE SETTINGS
# --------------------
# How many browser windows to run at once (more = faster but uses more RAM)
# Recommended: 8 for most computers, reduce to 4 if you have <8GB RAM
NUM_WORKERS = 8

# How many awards to buffer before writing to disk
# Lower = safer (less data loss on crash) but slower
SAVE_INTERVAL = 100

# WEBSITE URL
# -----------
# Base URL for grantee detail pages on the GATA website
BASE_URL = 'https://omb.illinois.gov/public/gata/csfa/Grantee.aspx'

# =============================================================================
# FILE PATHS - Automatically finds files in the script's folder
# =============================================================================
# The script uses relative paths based on where the .rb file is located.
# This means you can move the folder anywhere and it will still work.

# Where is this script located?
SCRIPT_DIR = File.dirname(File.expand_path(__FILE__))

# Input file: List of grantees to scrape (one per row with Grantee_ID and Grantee_Name)
MASTER_LIST = File.join(SCRIPT_DIR, 'grantee_master_list.csv')

# Output file: All scraped award data gets written here
OUTPUT_FILE = File.join(SCRIPT_DIR, 'gata_awards_FINAL.csv')

# Progress file: Tracks which grantee we're on (for resume capability)
PROGRESS_FILE = File.join(SCRIPT_DIR, 'scrape_progress.txt')

# =============================================================================
# DATA SOURCE ATTRIBUTION
# =============================================================================
# These values are added to every row so you know where the data came from

SOURCE = 'State of Illinois Grant Accountability and Transparency Act'
SOURCE_URL = 'https://gata.illinois.gov/grants/csfa.html'

# =============================================================================
# OUTPUT COLUMNS - These are the column headers in the output CSV file
# =============================================================================
# They use underscores instead of spaces so they work well in SQL databases.

CSV_COLUMNS = [
  'Grantee_ID',       # Unique identifier for the grantee (from URL parameter)
  'Grantee_Name',     # Organization name
  'Grantee_URL',      # Direct link to grantee's page on GATA website
  'Address',          # Street address (may be empty)
  'City_State_Zip',   # City, state and ZIP code (may be empty)
  'Fiscal_Year',      # State fiscal year (e.g., 2025)
  'Award_ID',         # Award identification number (may be blank)
  'Program',          # Grant program name
  'Agency',           # State agency providing the grant
  'Start_Date',       # Award start date (MM-DD-YYYY format)
  'End_Date',         # Award end date (MM-DD-YYYY format)
  'Amount',           # Dollar amount of the award (formatted with commas)
  'Source',           # Data source attribution
  'Source_URL'        # Link to GATA portal
]

# =============================================================================
# TERMINAL COLORS - Makes the progress display look nice
# =============================================================================
# These are ANSI escape codes that tell the terminal to display colored text.
# You don't need to understand these - they just make the output prettier.

module Colors
  RESET       = "\e[0m"   # Back to default color
  BOLD        = "\e[1m"   # Bold text
  DIM         = "\e[2m"   # Dimmed/gray text
  
  # Standard colors
  RED         = "\e[31m"
  GREEN       = "\e[32m"
  YELLOW      = "\e[33m"
  BLUE        = "\e[34m"
  CYAN        = "\e[36m"
  
  # Bright/intense colors (more visible)
  BRIGHT_GREEN  = "\e[92m"
  BRIGHT_YELLOW = "\e[93m"
  BRIGHT_CYAN   = "\e[96m"
end

# =============================================================================
# PROGRESS TRACKER CLASS
# =============================================================================
# This class keeps track of how many grantees we've processed, how many
# awards we've found, estimated time remaining, etc. It displays a nice
# progress bar in the terminal that updates as the scrape runs.
#
# THREAD SAFETY:
#   Multiple worker threads update this simultaneously, so we use
#   Concurrent::AtomicFixnum for counters (prevents race conditions)
#   and a Mutex for the display function (prevents garbled output).

class ProgressTracker
  attr_reader :total

  # ---------------------------------------------------------------------------
  # Initialize the progress tracker
  #
  # Arguments:
  #   total      - Total number of grantees to process
  #   start_from - Where to start (used when resuming an interrupted scrape)
  # ---------------------------------------------------------------------------
  def initialize(total, start_from = 0)
    @total = total
    @start_from = start_from
    
    # Atomic counters - thread-safe integers that can be updated by multiple threads
    @processed = Concurrent::AtomicFixnum.new(start_from)
    @errors    = Concurrent::AtomicFixnum.new(0)
    @awards    = Concurrent::AtomicFixnum.new(0)
    @workers   = Concurrent::AtomicFixnum.new(0)
    
    # Current stage shown in the display header
    @stage = 'Initializing'
    
    # Timing
    @start_time   = Time.now
    @last_display = Time.now - 10  # Force immediate display
    
    # Mutex prevents multiple threads from writing to terminal at once
    @display_mutex = Mutex.new
  end

  # ---------------------------------------------------------------------------
  # Getters and setters for the counters
  # ---------------------------------------------------------------------------
  
  def set_stage(stage)
    @stage = stage
  end
  
  def processed
    @processed.value
  end
  
  def increment_processed
    @processed.increment
  end
  
  def increment_errors
    @errors.increment
  end
  
  def add_awards(count)
    @awards.update { |current| current + count }
  end
  
  def awards_found
    @awards.value
  end
  
  def errors
    @errors.value
  end
  
  def increment_workers
    @workers.increment
  end
  
  def decrement_workers
    @workers.decrement
  end

  # ---------------------------------------------------------------------------
  # Calculate how long the scrape has been running
  # Returns a formatted string like "45m 30s" or "1h 23m"
  # ---------------------------------------------------------------------------
  def get_elapsed
    elapsed_seconds = (Time.now - @start_time).to_i
    hours   = elapsed_seconds / 3600
    minutes = (elapsed_seconds % 3600) / 60
    seconds = elapsed_seconds % 60
    
    if hours > 0
      "#{hours}h #{minutes}m"
    elsif minutes > 0
      "#{minutes}m #{seconds}s"
    else
      "#{seconds}s"
    end
  end

  # ---------------------------------------------------------------------------
  # Estimate time remaining based on current processing speed
  # Uses only grantees processed since resume (not total) for accuracy
  # ---------------------------------------------------------------------------
  def get_eta
    # How many have we processed since we started this session?
    new_processed = @processed.value - @start_from
    return '...' if new_processed < 1
    
    elapsed = Time.now - @start_time
    return '...' if elapsed < 1
    
    # Calculate rate and remaining time
    rate = new_processed.to_f / elapsed  # Grantees per second
    remaining = @total - @processed.value
    eta_seconds = remaining / rate
    
    if eta_seconds > 3600
      "#{(eta_seconds / 3600).to_i}h #{((eta_seconds % 3600) / 60).to_i}m"
    elsif eta_seconds > 60
      "#{(eta_seconds / 60).to_i}m"
    else
      "< 1m"
    end
  end

  # ---------------------------------------------------------------------------
  # Calculate processing speed in grantees per minute
  # ---------------------------------------------------------------------------
  def get_speed
    new_processed = @processed.value - @start_from
    elapsed = Time.now - @start_time
    return '--' if elapsed < 1 || new_processed < 1
    
    rate = (new_processed.to_f / elapsed) * 60  # Convert to per-minute
    "#{rate.round(1)}/min"
  end

  # ---------------------------------------------------------------------------
  # Display the progress dashboard in the terminal
  #
  # Creates a box with progress bar, stats, and ETA. Example:
  #
  #   +======================================================================+
  #   |  GATA SCRAPER (Ruby) [8 workers]            [Scraping]               |
  #   +======================================================================+
  #   |  Progress: [====================--------------------]  50.0%         |
  #   |  Grantees: 10,000 / 21,326                                           |
  #   |  Awards:   140,000  |  Errors: 0                                     |
  #   |  Elapsed:  45m 30s  |  ETA: 45m  |  Speed: 220/min                   |
  #   +======================================================================+
  #
  # Arguments:
  #   force - If true, always update. Otherwise, only update every 0.5 seconds.
  # ---------------------------------------------------------------------------
  def display(force: false)
    # Don't update too frequently (causes flickering)
    return unless force || (Time.now - @last_display) >= 0.5
    
    # Use mutex so only one thread can print at a time
    @display_mutex.synchronize do
      @last_display = Time.now
      
      # Calculate percentage complete
      pct = @total > 0 ? (@processed.value.to_f / @total * 100) : 0
      
      # Build the progress bar: [========----] style
      bar_width = 40
      filled = ((pct / 100.0) * bar_width).to_i
      bar = '=' * filled + '-' * (bar_width - filled)
      
      # Clear screen and move cursor to top-left
      # \e[2J = clear entire screen, \e[H = move cursor to home position
      print "\e[2J\e[H"
      
      # Print the dashboard box
      puts "+#{'=' * 70}+"
      puts "|  GATA SCRAPER (Ruby) [#{NUM_WORKERS} workers]            [#{@stage}]".ljust(71) + "|"
      puts "+#{'=' * 70}+"
      puts "|  Progress: [#{bar}] #{pct.round(1).to_s.rjust(5)}%   |"
      puts "|  Grantees: #{@processed.value} / #{@total}".ljust(71) + "|"
      puts "|  Awards:   #{@awards.value}  |  Errors: #{@errors.value}".ljust(71) + "|"
      puts "|  Elapsed:  #{get_elapsed}  |  ETA: #{get_eta}  |  Speed: #{get_speed}".ljust(71) + "|"
      puts "+#{'=' * 70}+"
    end
  end
end

# =============================================================================
# SCRAPING FUNCTION - Extracts all awards for a single grantee
# =============================================================================
# This is the core function that does the actual scraping. For each grantee:
#   1. Load their main page to get address info and list of fiscal years
#   2. For each fiscal year, reload the page with FY parameter
#   3. Extract all awards from the table
#   4. Return array of award records
#
# Arguments:
#   driver   - Selenium WebDriver instance (controls the browser)
#   grantee  - Hash with :id and :name keys
#   tracker  - ProgressTracker instance for error counting
#
# Returns:
#   Array of hashes, each representing one award record

def scrape_grantee(driver, grantee, tracker)
  grantee_id = grantee[:id]
  grantee_name = grantee[:name]
  
  # Build the URL for this grantee's page
  base_url = "#{BASE_URL}?id=#{grantee_id}"
  
  # This will hold all the award records we find
  results = []

  begin
    # -------------------------------------------------------------------------
    # STEP 1: Load the grantee's main page to get address and fiscal years
    # -------------------------------------------------------------------------
    driver.get(base_url)
    sleep(1.5)  # Wait for JavaScript to render

    # -------------------------------------------------------------------------
    # STEP 2: Extract address information from the page header
    # -------------------------------------------------------------------------
    # The header looks like:
    #   Organization Name
    #   123 Main Street
    #   Springfield, IL 62701
    address = ''
    city_state_zip = ''
    
    begin
      header = driver.find_element(id: 'lblGranteeHeader')
      lines = header.text.split("\n").map(&:strip).reject(&:empty?)
      
      # Line 0 = name, Line 1 = address, Line 2 = city/state/zip
      if lines.length >= 3
        address = lines[1]
        city_state_zip = lines[2]
      end
    rescue Selenium::WebDriver::Error::NoSuchElementError
      # Header element not found - leave address blank
    end

    # -------------------------------------------------------------------------
    # STEP 3: Get list of available fiscal years from the dropdown
    # -------------------------------------------------------------------------
    # The page has a dropdown (id="ddlFY") with all fiscal years that have data
    fiscal_years = []
    
    begin
      dropdown = driver.find_element(id: 'ddlFY')
      select = Selenium::WebDriver::Support::Select.new(dropdown)
      
      # Get all option values (skip empty values)
      fiscal_years = select.options
        .map { |opt| opt.attribute('value') }
        .reject { |v| v.nil? || v.empty? }
    rescue Selenium::WebDriver::Error::NoSuchElementError
      # No dropdown found - this grantee has no fiscal year data
    end

    # -------------------------------------------------------------------------
    # STEP 4: Handle grantees with no fiscal year data
    # -------------------------------------------------------------------------
    if fiscal_years.empty?
      # Create a placeholder record with empty award fields
      results << create_record(grantee_id, grantee_name, base_url, address, city_state_zip, '', {})
    else
      # -----------------------------------------------------------------------
      # STEP 5: For each fiscal year, load the page and extract awards
      # -----------------------------------------------------------------------
      # The GATA website uses URL parameters for fiscal year:
      # Grantee.aspx?id=12345&FY=2025
      
      fiscal_years.each do |fy|
        begin
          # Load page for this fiscal year
          driver.get("#{base_url}&FY=#{fy}")
          sleep(1.5)  # Wait for table to load

          # -------------------------------------------------------------------
          # STEP 6: Find the awards table
          # -------------------------------------------------------------------
          # IMPORTANT: The table ID is "tblList" (not "dgAwards" as you might expect!)
          table = driver.find_elements(id: 'tblList').first
          next unless table  # Skip if no table found

          # -------------------------------------------------------------------
          # STEP 7: Parse table rows
          # -------------------------------------------------------------------
          rows = table.find_elements(tag_name: 'tr')
          
          # Skip header row (first) and summary row (last)
          # data_rows = rows[1...-1] means "from index 1 to second-to-last"
          data_rows = rows[1...-1] || []

          # -------------------------------------------------------------------
          # STEP 8: Extract data from each row
          # -------------------------------------------------------------------
          data_rows.each do |row|
            cells = row.find_elements(tag_name: 'td')
            next if cells.length < 6  # Skip invalid rows

            # Table columns are:
            # [0] Award ID, [1] Program, [2] Agency, [3] Start Date, [4] End Date, [5] Amount
            results << create_record(
              grantee_id, grantee_name, base_url, address, city_state_zip, fy,
              {
                award_id:   cells[0].text.strip,
                program:    cells[1].text.strip,
                agency:     cells[2].text.strip,
                start_date: cells[3].text.strip,
                end_date:   cells[4].text.strip,
                amount:     cells[5].text.strip
              }
            )
          end
        rescue => e
          # Error loading this fiscal year - continue with next one
          next
        end
      end
    end

    # -------------------------------------------------------------------------
    # STEP 9: Ensure we always return at least one record per grantee
    # -------------------------------------------------------------------------
    # Even if a grantee has no awards, we want them in the output so we know
    # we processed them (useful for auditing completeness)
    if results.empty?
      results << create_record(grantee_id, grantee_name, base_url, address, city_state_zip, '', {})
    end

  rescue => e
    # -------------------------------------------------------------------------
    # ERROR HANDLING: If the whole grantee fails, log error and return placeholder
    # -------------------------------------------------------------------------
    tracker.increment_errors
    results = [create_record(grantee_id, grantee_name, base_url, '', '', '', {})]
  end

  results
end

# =============================================================================
# CREATE RECORD - Helper function to build a consistent record hash
# =============================================================================
# This function creates a hash with all the CSV columns properly filled in.
# Using a helper function ensures consistency and reduces code duplication.
#
# Arguments:
#   id      - Grantee ID
#   name    - Grantee name
#   url     - Full URL to grantee's page
#   address - Street address
#   csz     - City, state, zip
#   fy      - Fiscal year
#   award   - Hash with award details (or empty hash for placeholder)
#
# Returns:
#   Hash with all CSV columns as keys

def create_record(id, name, url, address, csz, fy, award)
  {
    'Grantee_ID'     => id,
    'Grantee_Name'   => name,
    'Grantee_URL'    => url,
    'Address'        => address,
    'City_State_Zip' => csz,
    'Fiscal_Year'    => fy,
    'Award_ID'       => award[:award_id]   || '',
    'Program'        => award[:program]    || '',
    'Agency'         => award[:agency]     || '',
    'Start_Date'     => award[:start_date] || '',
    'End_Date'       => award[:end_date]   || '',
    'Amount'         => award[:amount]     || '',
    'Source'         => SOURCE,
    'Source_URL'     => SOURCE_URL
  }
end

# =============================================================================
# WORKER FUNCTION - Runs in a separate thread to process grantees
# =============================================================================
# Each worker:
#   1. Creates its own browser instance (Chrome in headless mode)
#   2. Pulls grantees from the shared work queue
#   3. Scrapes each grantee and pushes results to the results queue
#   4. Continues until the work queue is empty
#
# Arguments:
#   worker_id     - Numeric ID for this worker (0-7 with 8 workers)
#   queue         - Thread-safe queue of grantees to process
#   results_queue - Thread-safe queue where results are pushed
#   tracker       - ProgressTracker for stats and display

def worker(worker_id, queue, results_queue, tracker)
  # ---------------------------------------------------------------------------
  # Configure Chrome options for headless scraping
  # ---------------------------------------------------------------------------
  options = Selenium::WebDriver::Chrome::Options.new
  
  # Run without visible window (headless mode)
  options.add_argument('--headless')
  
  # Required for running in containers/VMs
  options.add_argument('--no-sandbox')
  options.add_argument('--disable-dev-shm-usage')
  
  # Reduce log noise in terminal
  options.add_argument('--log-level=3')
  
  # Disable GPU (not needed for scraping, reduces errors)
  options.add_argument('--disable-gpu')

  # ---------------------------------------------------------------------------
  # Start the browser
  # ---------------------------------------------------------------------------
  driver = Selenium::WebDriver.for :chrome, options: options
  tracker.increment_workers

  # ---------------------------------------------------------------------------
  # Main processing loop
  # ---------------------------------------------------------------------------
  loop do
    # Try to get next grantee from queue (non-blocking)
    grantee = queue.pop(true) rescue nil
    break if grantee.nil?  # Queue is empty, exit loop

    # Scrape this grantee
    results = scrape_grantee(driver, grantee, tracker)
    
    # Push results to the results queue for the writer thread
    results_queue << results
    
    # Update progress
    tracker.add_awards(results.length)
    tracker.increment_processed
    tracker.display
  end

  # ---------------------------------------------------------------------------
  # Cleanup
  # ---------------------------------------------------------------------------
  tracker.decrement_workers
  driver.quit
  
rescue => e
  # If anything goes wrong, make sure we clean up
  tracker.decrement_workers
  driver&.quit rescue nil
end

# =============================================================================
# RESULTS WRITER - Runs in a separate thread to write CSV output
# =============================================================================
# Having a dedicated writer thread prevents I/O from blocking the workers.
# Results are buffered and written in batches for efficiency.
#
# Arguments:
#   results_queue - Queue where workers push their results
#   tracker       - ProgressTracker (not used here but kept for consistency)
#   first_write   - If true, write CSV header; if false, append only
#   done_flag     - Atomic boolean that signals when all workers are done

def results_writer(results_queue, tracker, first_write, done_flag)
  buffer = []           # Accumulate results before writing
  rows_written = 0      # Track total rows written

  loop do
    begin
      # Try to get results from queue (non-blocking)
      results = results_queue.pop(true)
      buffer.concat(results)

      # Write to disk when buffer reaches SAVE_INTERVAL
      if buffer.length >= SAVE_INTERVAL
        write_buffer(buffer, first_write && rows_written == 0)
        rows_written += buffer.length
        buffer = []  # Clear buffer after writing
      end
      
    rescue ThreadError
      # Queue is empty - check if we should exit or wait
      break if done_flag.value && results_queue.empty?
      sleep(0.1)  # Wait a bit before checking again
    end
  end

  # Write any remaining buffered results
  if buffer.any?
    write_buffer(buffer, first_write && rows_written == 0)
    rows_written += buffer.length
  end

  rows_written
end

# =============================================================================
# WRITE BUFFER - Helper function to write results to CSV file
# =============================================================================
# Arguments:
#   buffer       - Array of record hashes to write
#   write_header - If true, write the CSV header row first

def write_buffer(buffer, write_header)
  # 'w' = overwrite (for first write), 'a' = append (for subsequent writes)
  mode = write_header ? 'w' : 'a'
  
  CSV.open(OUTPUT_FILE, mode, encoding: 'utf-8') do |csv|
    # Write header row if this is the first write
    csv << CSV_COLUMNS if write_header
    
    # Write each record as a row
    buffer.each do |row|
      csv << CSV_COLUMNS.map { |col| row[col] }
    end
  end
end

# =============================================================================
# PROGRESS SAVE/LOAD FUNCTIONS - For resume capability
# =============================================================================

# Load saved progress (returns nil if no progress file exists)
def load_progress
  return nil unless File.exist?(PROGRESS_FILE)
  File.read(PROGRESS_FILE).to_i
end

# Save current progress to file
def save_progress(index)
  File.write(PROGRESS_FILE, index.to_s)
end

# =============================================================================
# LOAD GRANTEE LIST - Reads the input CSV file
# =============================================================================
# Returns an array of hashes: [{id: '12345', name: 'Org Name'}, ...]

def load_grantee_list
  grantees = []
  
  CSV.foreach(MASTER_LIST, headers: true, encoding: 'utf-8') do |row|
    grantees << {
      id: row['Grantee_ID'],
      name: row['Grantee_Name']
    }
  end
  
  grantees
end

# =============================================================================
# MAIN FUNCTION - Orchestrates the entire scraping process
# =============================================================================
# This is the entry point that sets everything up and coordinates the scrape:
#   1. Load grantee list and check for resume
#   2. Set up work queue, results queue, and progress tracker
#   3. Start worker threads and writer thread
#   4. Wait for completion
#   5. Display final results

def main
  # ---------------------------------------------------------------------------
  # STARTUP: Print welcome message
  # ---------------------------------------------------------------------------
  puts "\n#{Colors::CYAN}GATA Grantee Scraper - Ruby (Selenium)#{Colors::RESET}"
  puts "=" * 50

  # ---------------------------------------------------------------------------
  # LOAD: Read the grantee list from CSV
  # ---------------------------------------------------------------------------
  grantees = load_grantee_list
  total = grantees.length
  puts "Loaded #{total} grantees"
  puts "Using #{NUM_WORKERS} parallel workers"

  # ---------------------------------------------------------------------------
  # RESUME: Check if we have saved progress from a previous run
  # ---------------------------------------------------------------------------
  start_index = load_progress || 0
  first_write = true  # Should we write CSV header?

  if start_index > 0 && start_index < total
    puts "#{Colors::YELLOW}Resuming from grantee #{start_index + 1}#{Colors::RESET}"
    grantees = grantees[start_index..]  # Skip already-processed grantees
    first_write = false  # Don't overwrite existing data
  end

  # ---------------------------------------------------------------------------
  # SETUP: Create progress tracker and work queues
  # ---------------------------------------------------------------------------
  tracker = ProgressTracker.new(total, start_index)
  tracker.set_stage('Scraping')

  # Thread-safe queues for work distribution and result collection
  work_queue = Queue.new
  results_queue = Queue.new
  
  # Atomic boolean to signal when all workers are done
  done_flag = Concurrent::AtomicBoolean.new(false)

  # Add all grantees to the work queue
  grantees.each { |g| work_queue << g }

  puts "#{Colors::GREEN}Starting workers...#{Colors::RESET}\n"
  sleep(1)  # Brief pause for visual feedback

  # ---------------------------------------------------------------------------
  # THREADS: Start worker threads, writer thread, and progress saver
  # ---------------------------------------------------------------------------
  
  # Worker threads - each one scrapes grantees from the queue
  workers = NUM_WORKERS.times.map do |i|
    Thread.new { worker(i, work_queue, results_queue, tracker) }
  end
  
  # Writer thread - collects results and writes to CSV
  writer_thread = Thread.new do
    results_writer(results_queue, tracker, first_write, done_flag)
  end
  
  # Saver thread - saves progress every 30 seconds
  saver_thread = Thread.new do
    loop do
      save_progress(tracker.processed)
      sleep(30)
      break if done_flag.value
    end
  end

  # ---------------------------------------------------------------------------
  # WAIT: Wait for all workers to finish
  # ---------------------------------------------------------------------------
  workers.each(&:join)
  
  # Signal that all workers are done
  done_flag.make_true
  
  # Wait for writer to finish flushing buffer
  writer_thread.join
  
  # Stop the saver thread
  saver_thread.kill

  # ---------------------------------------------------------------------------
  # COMPLETE: Show final results
  # ---------------------------------------------------------------------------
  tracker.set_stage('Complete')
  tracker.display(force: true)
  
  # Save final progress
  save_progress(total)

  puts "\n#{Colors::BRIGHT_GREEN}Scrape complete!#{Colors::RESET}"
  puts "Output: #{OUTPUT_FILE}"
  puts "Awards: #{tracker.awards_found}"
  puts "Time: #{tracker.get_elapsed}"

  # Clean up progress file (scrape is complete, no need to resume)
  File.delete(PROGRESS_FILE) if File.exist?(PROGRESS_FILE)
end

# =============================================================================
# ENTRY POINT - Only run main() if this file is executed directly
# =============================================================================
# This check allows the file to be loaded in irb/pry for testing without
# automatically starting the scrape.

if __FILE__ == $0
  main
end
