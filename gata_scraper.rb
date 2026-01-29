# =============================================================================
# GATA GRANTEE SCRAPER - RUBY VERSION (SELENIUM)
# =============================================================================
# This script scrapes Illinois GATA (Grant Accountability & Transparency Act)
# grantee data from https://omb.illinois.gov/public/gata/csfa/
#
# WHAT IT DOES:
#   1. Reads a list of grantees from grantee_master_list.csv
#   2. Visits each grantee's page on the GATA website
#   3. Loads each fiscal year via URL parameters
#   4. Saves all award data to gata_awards_FINAL.csv
#
# HOW TO RUN:
#   1. Install Ruby (https://rubyinstaller.org/ for Windows)
#   2. Install gems: gem install selenium-webdriver concurrent-ruby
#   3. Run: ruby gata_scraper.rb
#
# REQUIREMENTS:
#   - Ruby 3.0+
#   - Chrome/Chromium browser installed
#   - Gems: selenium-webdriver, concurrent-ruby
#
# CREATED: January 2026
# =============================================================================

require 'selenium-webdriver'
require 'csv'
require 'concurrent'

# =============================================================================
# CONFIGURATION
# =============================================================================

# Number of parallel browser instances
NUM_WORKERS = 8

# How often to save results to disk
SAVE_INTERVAL = 100

# Base URL for grantee pages
BASE_URL = 'https://omb.illinois.gov/public/gata/csfa/Grantee.aspx'

# =============================================================================
# FILE PATHS - Uses relative paths from script location
# =============================================================================

SCRIPT_DIR = File.dirname(File.expand_path(__FILE__))
MASTER_LIST = File.join(SCRIPT_DIR, 'grantee_master_list.csv')
OUTPUT_FILE = File.join(SCRIPT_DIR, 'gata_awards_FINAL.csv')
PROGRESS_FILE = File.join(SCRIPT_DIR, 'scrape_progress.txt')

# =============================================================================
# CSV OUTPUT COLUMNS
# =============================================================================

CSV_COLUMNS = [
  'Grantee_ID', 'Grantee_Name', 'Grantee_URL', 'Address', 'City_State_Zip',
  'Fiscal_Year', 'Award_ID', 'Program', 'Agency', 'Start_Date', 'End_Date',
  'Amount', 'Source', 'Source_URL'
]

# =============================================================================
# ANSI COLOR CODES
# =============================================================================

module Colors
  RESET = "\e[0m"
  GREEN = "\e[32m"
  YELLOW = "\e[33m"
  CYAN = "\e[36m"
  BRIGHT_GREEN = "\e[92m"
end

# =============================================================================
# PROGRESS TRACKER
# =============================================================================

class ProgressTracker
  attr_reader :total

  def initialize(total, start_from = 0)
    @total = total
    @processed = Concurrent::AtomicFixnum.new(start_from)
    @errors = Concurrent::AtomicFixnum.new(0)
    @awards = Concurrent::AtomicFixnum.new(0)
    @workers = Concurrent::AtomicFixnum.new(0)
    @stage = 'Initializing'
    @start_time = Time.now
    @last_display = Time.now - 10
    @mutex = Mutex.new
  end

  def set_stage(s) @stage = s end
  def processed() @processed.value end
  def increment_processed() @processed.increment end
  def increment_errors() @errors.increment end
  def add_awards(n) @awards.update { |v| v + n } end
  def awards_found() @awards.value end
  def errors() @errors.value end
  def increment_workers() @workers.increment end
  def decrement_workers() @workers.decrement end

  def get_elapsed
    elapsed = (Time.now - @start_time).to_i
    h, m, s = elapsed / 3600, (elapsed % 3600) / 60, elapsed % 60
    h > 0 ? "#{h}h #{m}m" : m > 0 ? "#{m}m #{s}s" : "#{s}s"
  end

  def display(force: false)
    return unless force || (Time.now - @last_display) >= 0.5
    @mutex.synchronize do
      @last_display = Time.now
      pct = @total > 0 ? (@processed.value.to_f / @total * 100) : 0
      bar_width, filled = 40, ((pct / 100.0) * 40).to_i
      bar = '=' * filled + '-' * (bar_width - filled)
      
      elapsed = Time.now - @start_time
      if @processed.value > 0 && elapsed > 0
        rate = @processed.value / elapsed
        eta_secs = (@total - @processed.value) / rate
        eta = eta_secs > 60 ? "#{(eta_secs/60).to_i}m" : "< 1m"
        speed = "#{(rate * 60).round(1)}/min"
      else
        eta, speed = "...", "--"
      end

      print "\e[2J\e[H"
      puts "+#{'='*70}+"
      puts "|  GATA SCRAPER (Ruby) [#{NUM_WORKERS} workers]            [#{@stage}]".ljust(71)+"|"
      puts "+#{'='*70}+"
      puts "|  Progress: [#{bar}] #{pct.round(1).to_s.rjust(5)}%   |"
      puts "|  Grantees: #{@processed.value} / #{@total}".ljust(71)+"|"
      puts "|  Awards:   #{@awards.value}  |  Errors: #{@errors.value}".ljust(71)+"|"
      puts "|  Elapsed:  #{get_elapsed}  |  ETA: #{eta}  |  Speed: #{speed}".ljust(71)+"|"
      puts "+#{'='*70}+"
    end
  end
end

# =============================================================================
# SCRAPING FUNCTION
# =============================================================================

def scrape_grantee(driver, grantee, tracker)
  grantee_id = grantee[:id]
  grantee_name = grantee[:name]
  base_url = "#{BASE_URL}?id=#{grantee_id}"
  results = []

  begin
    # Load initial page to get grantee info and fiscal years
    driver.get(base_url)
    sleep(1.5)

    # Get address info
    address, city_state_zip = '', ''
    begin
      header = driver.find_element(id: 'lblGranteeHeader')
      lines = header.text.split("\n").map(&:strip).reject(&:empty?)
      if lines.length >= 3
        address = lines[1]
        city_state_zip = lines[2]
      end
    rescue Selenium::WebDriver::Error::NoSuchElementError
      # No header found
    end

    # Get fiscal years from dropdown
    fiscal_years = []
    begin
      dropdown = driver.find_element(id: 'ddlFY')
      select = Selenium::WebDriver::Support::Select.new(dropdown)
      fiscal_years = select.options.map { |o| o.attribute('value') }.reject { |v| v.nil? || v.empty? }
    rescue Selenium::WebDriver::Error::NoSuchElementError
      # No dropdown
    end

    if fiscal_years.empty?
      # No fiscal years - record grantee with empty award data
      results << create_record(grantee_id, grantee_name, base_url, address, city_state_zip, '', {})
    else
      # Iterate through each fiscal year using URL parameters
      fiscal_years.each do |fy|
        begin
          driver.get("#{base_url}&FY=#{fy}")
          sleep(1.5)

          # The awards table has id="tblList" (NOT dgAwards!)
          table = driver.find_elements(id: 'tblList').first
          next unless table

          rows = table.find_elements(tag_name: 'tr')
          # Skip header row and summary row (last row)
          data_rows = rows[1...-1] || []

          data_rows.each do |row|
            cells = row.find_elements(tag_name: 'td')
            next if cells.length < 6

            results << create_record(
              grantee_id, grantee_name, base_url, address, city_state_zip, fy,
              {
                award_id: cells[0].text.strip,
                program: cells[1].text.strip,
                agency: cells[2].text.strip,
                start_date: cells[3].text.strip,
                end_date: cells[4].text.strip,
                amount: cells[5].text.strip
              }
            )
          end
        rescue => e
          # Continue with next fiscal year
          next
        end
      end
    end

    # If no awards found, create placeholder
    if results.empty?
      results << create_record(grantee_id, grantee_name, base_url, address, city_state_zip, '', {})
    end

  rescue => e
    tracker.increment_errors
    results = [create_record(grantee_id, grantee_name, base_url, '', '', '', {})]
  end

  results
end

def create_record(id, name, url, address, csz, fy, award)
  {
    'Grantee_ID' => id,
    'Grantee_Name' => name,
    'Grantee_URL' => url,
    'Address' => address,
    'City_State_Zip' => csz,
    'Fiscal_Year' => fy,
    'Award_ID' => award[:award_id] || '',
    'Program' => award[:program] || '',
    'Agency' => award[:agency] || '',
    'Start_Date' => award[:start_date] || '',
    'End_Date' => award[:end_date] || '',
    'Amount' => award[:amount] || '',
    'Source' => 'State of Illinois Grant Accountability and Transparency Act',
    'Source_URL' => 'https://gata.illinois.gov/grants/csfa.html'
  }
end

# =============================================================================
# WORKER FUNCTION
# =============================================================================

def worker(worker_id, queue, results_queue, tracker)
  options = Selenium::WebDriver::Chrome::Options.new
  options.add_argument('--headless')
  options.add_argument('--no-sandbox')
  options.add_argument('--disable-dev-shm-usage')
  options.add_argument('--log-level=3')
  options.add_argument('--disable-gpu')

  driver = Selenium::WebDriver.for :chrome, options: options
  tracker.increment_workers

  loop do
    grantee = queue.pop(true) rescue nil
    break if grantee.nil?

    results = scrape_grantee(driver, grantee, tracker)
    results_queue << results
    tracker.add_awards(results.length)
    tracker.increment_processed
    tracker.display
  end

  tracker.decrement_workers
  driver.quit
rescue => e
  tracker.decrement_workers
  driver&.quit rescue nil
end

# =============================================================================
# RESULTS WRITER
# =============================================================================

def results_writer(results_queue, tracker, first_write, done_flag)
  buffer = []
  rows_written = 0

  loop do
    begin
      results = results_queue.pop(true)
      buffer.concat(results)

      if buffer.length >= SAVE_INTERVAL
        write_buffer(buffer, first_write && rows_written == 0)
        rows_written += buffer.length
        buffer = []
      end
    rescue ThreadError
      break if done_flag.value && results_queue.empty?
      sleep(0.1)
    end
  end

  if buffer.any?
    write_buffer(buffer, first_write && rows_written == 0)
    rows_written += buffer.length
  end

  rows_written
end

def write_buffer(buffer, write_header)
  mode = write_header ? 'w' : 'a'
  CSV.open(OUTPUT_FILE, mode, encoding: 'utf-8') do |csv|
    csv << CSV_COLUMNS if write_header
    buffer.each { |row| csv << CSV_COLUMNS.map { |col| row[col] } }
  end
end

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def load_progress
  return nil unless File.exist?(PROGRESS_FILE)
  File.read(PROGRESS_FILE).to_i
end

def save_progress(index)
  File.write(PROGRESS_FILE, index.to_s)
end

def load_grantee_list
  grantees = []
  CSV.foreach(MASTER_LIST, headers: true, encoding: 'utf-8') do |row|
    grantees << { id: row['Grantee_ID'], name: row['Grantee_Name'] }
  end
  grantees
end

# =============================================================================
# MAIN FUNCTION
# =============================================================================

def main
  puts "\n#{Colors::CYAN}GATA Grantee Scraper - Ruby (Selenium)#{Colors::RESET}"
  puts "=" * 50

  grantees = load_grantee_list
  total = grantees.length
  puts "Loaded #{total} grantees"
  puts "Using #{NUM_WORKERS} parallel workers"

  start_index = load_progress || 0
  first_write = true

  if start_index > 0 && start_index < total
    puts "#{Colors::YELLOW}Resuming from #{start_index + 1}#{Colors::RESET}"
    grantees = grantees[start_index..]
    first_write = false
  end

  tracker = ProgressTracker.new(total, start_index)
  tracker.set_stage('Scraping')

  work_queue = Queue.new
  results_queue = Queue.new
  done_flag = Concurrent::AtomicBoolean.new(false)

  grantees.each { |g| work_queue << g }

  puts "#{Colors::GREEN}Starting workers...#{Colors::RESET}\n"
  sleep(1)

  workers = NUM_WORKERS.times.map { |i| Thread.new { worker(i, work_queue, results_queue, tracker) } }
  writer_thread = Thread.new { results_writer(results_queue, tracker, first_write, done_flag) }
  saver_thread = Thread.new { loop { save_progress(tracker.processed); sleep(30); break if done_flag.value } }

  workers.each(&:join)
  done_flag.make_true
  writer_thread.join
  saver_thread.kill

  tracker.set_stage('Complete')
  tracker.display(force: true)
  save_progress(total)

  puts "\n#{Colors::BRIGHT_GREEN}Scrape complete!#{Colors::RESET}"
  puts "Output: #{OUTPUT_FILE}"
  puts "Awards: #{tracker.awards_found}"
  puts "Time: #{tracker.get_elapsed}"

  File.delete(PROGRESS_FILE) if File.exist?(PROGRESS_FILE)
end

if __FILE__ == $0
  main
end
