# type: ignore

"""
Enables the automation of searching for multiple makes/models on Autotrader UK using Selenium and Regex.

Set your criteria and cars makes/models.

Data is then output to an Excel file in the same directory.

Running Chrome Version 119.0.6045.106 and using Stable Win64 ChromeDriver from:
https://googlechromelabs.github.io/chrome-for-testing/
https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/119.0.6045.105/win64/chromedriver-win64.zip
"""
import os
import re
import time
import datetime
import logging
import subprocess
import requests
import json
from pathlib import Path
from packaging import version
import bs4
import urllib.parse
import random
import sys

import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import SessionNotCreatedException
from selenium.webdriver.common.timeouts import Timeouts
import socket
import urllib3
import psutil


def setup_logging():
    """
    Configure logging to output to both file and console with timestamps.
    """
    # Create logs directory if it doesn't exist
    log_dir = Path("output/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Create a log file with timestamp
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"autotrader_scraper_{timestamp}.log"
    
    # Configure logging format and level
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)  # Use sys.stdout explicitly for console output
        ]
    )
    
    # Force UTF-8 encoding for all handlers
    for handler in logging.root.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.stream.reconfigure(encoding='utf-8')
    
    logging.info(f"Logging initialized. Log file: {log_file}")

def get_chrome_version():
    """
    Get the installed Chrome browser version.
    Returns version string or None if Chrome is not found.
    """
    try:
        if os.name == 'nt':  # Windows
            # Try multiple methods to get Chrome version on Windows
            possible_paths = [
                Path(r'C:\Program Files\Google\Chrome\Application'),
                Path(r'C:\Program Files (x86)\Google\Chrome\Application'),
                Path.home() / 'AppData/Local/Google/Chrome/Application',
                Path(r'C:\Users\Default\AppData\Local\Google\Chrome\Application'),
                Path(r'D:\Program Files\Google\Chrome\Application'),
                Path(r'D:\Program Files (x86)\Google\Chrome\Application')
            ]
            
            logging.info("Searching for Chrome in common locations...")
            for chrome_path in possible_paths:
                logging.debug(f"Checking path: {chrome_path}")
                if chrome_path.exists():
                    logging.info(f"Found Chrome at: {chrome_path}")
                    
                    # Look for version directory
                    try:
                        # Get all subdirectories that look like version numbers
                        version_dirs = [d for d in chrome_path.iterdir() 
                                     if d.is_dir() and re.match(r'^\d+\.\d+\.\d+\.\d+$', d.name)]
                        
                        if version_dirs:
                            # Sort version directories to get the latest one
                            latest_version = sorted(version_dirs, key=lambda x: [int(p) for p in x.name.split('.')])[-1]
                            version = latest_version.name
                            logging.info(f"Found Chrome version {version} in directory structure")
                            return version
                            
                    except (PermissionError, OSError) as e:
                        logging.debug(f"Error checking version directories: {e}")
                        continue

            # Fallback: Try to find chrome.exe and check its version
            chrome_exe_paths = [
                p / 'chrome.exe' for p in possible_paths
                if (p / 'chrome.exe').exists()
            ]
            
            if chrome_exe_paths:
                chrome_exe = chrome_exe_paths[0]
                try:
                    # Use a minimal PowerShell command
                    cmd = f'powershell.exe -NoProfile -Command "(Get-Item \'{chrome_exe}\').VersionInfo.ProductVersion"'
                    output = subprocess.check_output(
                        cmd,
                        shell=True,
                        text=True,
                        stderr=subprocess.PIPE
                    )
                    version = output.strip()
                    if version and re.match(r'^\d+\.\d+\.\d+\.\d+$', version):
                        logging.info(f"Found Chrome version {version} from executable")
                        return version
                except subprocess.CalledProcessError as e:
                    logging.debug(f"Error getting version from executable: {e}")

        else:  # Linux/Mac
            try:
                output = subprocess.check_output(['google-chrome', '--version'], text=True)
                version_match = re.search(r'Chrome\s+([\d.]+)', output)
                if version_match:
                    version = version_match.group(1)
                    logging.info(f"Found Chrome version {version}")
                    return version
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                logging.debug(f"Linux/Mac version check failed: {e}")

        logging.error("Could not detect Chrome version using any available method")
        return None
    except Exception as e:
        logging.error(f"Error getting Chrome version: {str(e)}")
        return None

def get_compatible_driver_version(chrome_version):
    """
    Maps Chrome version to a compatible ChromeDriver version.
    Uses known stable versions from Chrome for Testing.
    """
    try:
        major_version = int(chrome_version.split('.')[0])
        
        # Known stable Chrome for Testing versions
        version_map = {
            137: "137.0.7151.40",  # Beta version
            136: "136.0.7103.113", # Stable version
            135: "135.0.7071.100", # Previous stable
            134: "134.0.7066.100",
            133: "133.0.7047.100",
            132: "132.0.7037.100",
            131: "131.0.7029.100",
            130: "130.0.7021.100",
            129: "129.0.7011.100",
            128: "128.0.6999.100",
            127: "127.0.6988.100",
            # Add more versions as needed
        }
        
        # If exact major version is found, use it
        if major_version in version_map:
            return version_map[major_version]
            
        # For versions older than our map
        if major_version < min(version_map.keys()):
            return "109.0.5414.74"  # Last version before Chrome for Testing
            
        # For newer versions, use latest stable
        return "136.0.7103.113"
            
    except (ValueError, IndexError) as e:
        logging.error(f"Error parsing Chrome version: {e}")
        return "136.0.7103.113"  # Default to latest stable

def download_chromedriver(chrome_version):
    """
    Download the appropriate ChromeDriver version for the installed Chrome.
    Returns the path to the downloaded ChromeDriver.
    """
    try:
        # Create drivers directory if it doesn't exist
        driver_dir = Path("output/drivers")
        driver_dir.mkdir(parents=True, exist_ok=True)

        # Get compatible driver version
        driver_version = get_compatible_driver_version(chrome_version)
        logging.info(f"Using ChromeDriver version {driver_version} for Chrome {chrome_version}")
        
        # Determine if we should use old or new download URL format
        use_old_format = driver_version.startswith("109.")
        platform = 'win64'  # We know we're on Windows
        driver_name = 'chromedriver.exe'
        
        if use_old_format:
            # Old ChromeDriver CDN format
            download_url = f"https://chromedriver.storage.googleapis.com/{driver_version}/chromedriver_win32.zip"
            logging.info("Using legacy ChromeDriver CDN")
        else:
            # New Chrome for Testing storage format
            download_url = f"https://storage.googleapis.com/chrome-for-testing-public/{driver_version}/{platform}/chromedriver-{platform}.zip"
            logging.info("Using Chrome for Testing storage")
        
        # Download and extract ChromeDriver
        driver_path = driver_dir / driver_name
        if not driver_path.exists():
            logging.info(f"Downloading ChromeDriver from: {download_url}")
            try:
                response = requests.get(download_url)
                response.raise_for_status()  # Raise an error for bad status codes
                
                zip_path = driver_dir / "chromedriver.zip"
                with open(zip_path, 'wb') as f:
                    f.write(response.content)
                
                # Extract the zip file
                import zipfile
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    if use_old_format:
                        # Old format: chromedriver.exe is at root of zip
                        zip_ref.extractall(driver_dir)
                    else:
                        # New format: includes a chromedriver directory
                        zip_ref.extractall(driver_dir)
                        # Move the chromedriver from the nested directory
                        chromedriver_dir = driver_dir / f"chromedriver-{platform}"
                        if chromedriver_dir.exists():
                            nested_driver = chromedriver_dir / driver_name
                            if nested_driver.exists():
                                import shutil
                                shutil.move(str(nested_driver), str(driver_path))
                                shutil.rmtree(str(chromedriver_dir))
                
                # Clean up zip file
                zip_path.unlink()
                
            except requests.exceptions.RequestException as e:
                logging.error(f"Failed to download ChromeDriver: {e}")
                if not driver_path.exists():
                    raise Exception("Failed to download ChromeDriver and no existing driver found")
        
        return str(driver_path)
    except Exception as e:
        logging.error(f"Error downloading ChromeDriver: {str(e)}")
        return None

def initialize_webdriver():
    """
    Initialize the Chrome WebDriver with version checking and compatibility handling.
    Returns the WebDriver instance or raises an exception if initialization fails.
    """
    logging.info("Checking Chrome version...")
    chrome_version = get_chrome_version()
    
    if not chrome_version:
        # Fallback: Use a known stable version
        chrome_version = "120.0.6099.71"
        logging.warning(f"Could not detect Chrome version, using fallback version {chrome_version}")
    
    logging.info(f"Using Chrome version: {chrome_version}")
    
    # Download matching ChromeDriver
    driver_path = download_chromedriver(chrome_version)
    if not driver_path:
        raise Exception("Failed to download compatible ChromeDriver.")
    
    logging.info(f"Using ChromeDriver at: {driver_path}")

    # Kill any existing ChromeDriver and Chrome processes
    def kill_processes(process_names):
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                for name in process_names:
                    if name.lower() in proc.info['name'].lower():
                        logging.info(f"Killing process {proc.info['name']} (PID: {proc.info['pid']})")
                        psutil.Process(proc.info['pid']).kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

    try:
        kill_processes(['chromedriver', 'chrome.exe'])
        time.sleep(2)  # Give time for processes to fully terminate
    except Exception as e:
        logging.warning(f"Error killing processes: {e}")

    # Set up Chrome options with stealth settings
    chrome_options = Options()
    
    # Set page load strategy to eager (don't wait for all resources)
    chrome_options.page_load_strategy = 'eager'
    
    # Essential settings for stability
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-popup-blocking")
    
    # Network settings
    chrome_options.add_argument("--dns-prefetch-disable")  # Disable DNS prefetch
    chrome_options.add_argument("--no-proxy-server")      # Disable proxy
    chrome_options.add_argument("--disable-http2")        # Disable HTTP/2
    chrome_options.add_argument("--disable-ipv6")         # Disable IPv6
    
    # Stealth settings to avoid detection
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    
    # Make the browser more realistic
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--start-maximized")
    
    # Set realistic user agent
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    # Additional stealth settings
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-web-security")
    chrome_options.add_argument("--disable-site-isolation-trials")
    chrome_options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    
    # Disable unwanted features and logging
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--silent")
    chrome_options.add_argument("--disable-infobars")
    
    # Performance settings
    chrome_options.add_argument("--disable-gpu-shader-disk-cache")
    chrome_options.add_argument("--disable-application-cache")
    chrome_options.add_argument("--disable-default-apps")
    chrome_options.add_argument("--disable-sync")
    
    # Add preferences for better stability and stealth
    chrome_options.add_experimental_option("prefs", {
        "profile.default_content_settings.cookies": 1,
        "profile.cookie_controls_mode": 0,
        "profile.block_third_party_cookies": False,
        "profile.default_content_setting_values": {
            "cookies": 1,
            "images": 1,
            "javascript": 1,
            "plugins": 2,
            "popups": 2,
            "notifications": 2,
            "auto_select_certificate": 2,
            "fullscreen": 2,
            "mouselock": 2,
            "mixed_script": 2,
            "media_stream": 2,
            "media_stream_mic": 2,
            "media_stream_camera": 2,
            "protocol_handlers": 2,
            "ppapi_broker": 2,
            "automatic_downloads": 2,
            "midi_sysex": 2,
            "push_messaging": 2,
            "ssl_cert_decisions": 2,
            "metro_switch_to_desktop": 2,
            "protected_media_identifier": 2,
            "app_banner": 2,
            "site_engagement": 2,
            "durable_storage": 2
        },
        "download_restrictions": 3,
        "credentials_enable_service": False,
        "extensions.ui.developer_mode": False,
        "extensions.logging.enabled": False,
        "webrtc.ip_handling_policy": "disable_non_proxied_udp",
        "profile.managed_default_content_settings.images": 1,
        "profile.managed_default_content_settings.javascript": 1,
        "profile.managed_default_content_settings.plugins": 2,
        "profile.managed_default_content_settings.popups": 2,
        "profile.managed_default_content_settings.geolocation": 2,
        "profile.managed_default_content_settings.media_stream": 2,
        "profile.default_content_settings.geolocation": 2,
        "profile.default_content_settings.notifications": 2,
        "profile.password_manager_enabled": False,
        "profile.content_settings.exceptions.plugins.*,*.per_resource.adobe-flash-player": 1,
        "profile.content_settings.exceptions.automatic_downloads": 2,
        "profile.content_settings.exceptions.client_hints": 2,
        "profile.content_settings.exceptions.media_engagement": 2,
        "profile.content_settings.exceptions.midi_sysex": 2,
        "profile.content_settings.exceptions.mixed_script": 2,
        "profile.content_settings.exceptions.protected_media_identifier": 2,
        "profile.content_settings.exceptions.site_engagement": 2
    })
    
    # Initialize WebDriver with retry logic
    max_retries = 3
    retry_delay = 5
    last_error = None

    def find_free_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            s.listen(1)
            port = s.getsockname()[1]
            return port

    for attempt in range(max_retries):
        driver = None
        service = None
        try:
            logging.info(f"Attempt {attempt + 1}/{max_retries} to start Chrome WebDriver")
            
            # Find a free port
            port = find_free_port()
            logging.info(f"Using port {port} for ChromeDriver")
            
            # Create service object pointing to the running ChromeDriver
            service = Service(
                executable_path=driver_path,
                port=port,
                log_output=os.path.join("output", "chromedriver.log")
            )
            
            # Initialize the driver
            driver = webdriver.Chrome(
                service=service,
                options=chrome_options
            )
            
            # Set timeouts using the new Timeouts API with shorter values
            timeouts = Timeouts()
            timeouts.page_load = 15000  # 15 seconds
            timeouts.implicit = 5000    # 5 seconds
            timeouts.script = 15000     # 15 seconds
            
            # Set timeouts with retry
            timeout_set = False
            for timeout_attempt in range(3):
                try:
                    driver.timeouts = timeouts
                    timeout_set = True
                    break
                except Exception as e:
                    if timeout_attempt == 2:
                        raise
                    logging.warning(f"Failed to set timeouts (attempt {timeout_attempt + 1}): {e}")
                    time.sleep(1)
            
            if not timeout_set:
                raise Exception("Failed to set timeouts after multiple attempts")
            
            # Test the browser with a simple navigation
            driver.get("https://www.google.com")
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            logging.info("Test navigation successful")
            
            # Execute CDP commands to make the browser more realistic
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });
                    window.chrome = {
                        runtime: {}
                    };
                """
            })
            
            logging.info("Chrome WebDriver successfully initialized")
            return driver
            
        except Exception as e:
            logging.error(f"Failed to initialize Chrome WebDriver (Attempt {attempt + 1}/{max_retries})")
            logging.error(f"Error: {str(e)}")
            
            # Cleanup
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            
            if service:
                try:
                    service.stop()
                except:
                    pass
            
            if attempt < max_retries - 1:
                logging.info(f"Waiting {retry_delay} seconds before retrying...")
                time.sleep(retry_delay)
                retry_delay *= 2
            last_error = e
            
            # Kill any remaining processes before next attempt
            kill_processes(['chromedriver', 'chrome.exe'])
            time.sleep(2)

    raise Exception("Failed to initialize Chrome WebDriver after all attempts") from last_error

def load_page_with_retry(driver, url, max_retries=3):
    """Helper function to load a page with retry logic and cookie handling"""
    for attempt in range(max_retries):
        try:
            # Clear cookies and cache before loading new page
            driver.delete_all_cookies()
            
            # Check browser responsiveness
            driver.get("https://www.google.com")
            time.sleep(2)
            
            # Navigate to target URL
            logging.info(f"Loading page (attempt {attempt + 1}/{max_retries}): {url}")
            driver.get(url)
            
            # Wait for initial body tag to ensure page is loading
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Log page title and URL for debugging
            logging.info(f"Page Title: {driver.title}")
            logging.info(f"Current URL: {driver.current_url}")

            # Take a screenshot before looking for results
            try:
                screenshot_dir = Path("output/debug_screenshots")
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot_path = screenshot_dir / f"before_search_{timestamp}.png"
                driver.save_screenshot(str(screenshot_path))
                logging.info(f"Saved pre-search screenshot to {screenshot_path}")
            except Exception as e:
                logging.error(f"Failed to save screenshot: {e}")

            # Try to find any search-related elements first
            logging.info("Attempting to find search results container...")
            
            # Consolidated list of selectors for finding search results
            selectors = [
                "article[data-testid='search-result']",      # Primary selector for individual listings
                "div[data-testid='advertCard']",             # Alternative card format
                "div[data-testid='search-card']",            # Another possible card format
                "[data-testid='search-results']",            # Results container
                "div.infinite-scroll-component",             # Infinite scroll container
                "section[data-testid='desktop-search']"      # Desktop search section
            ]
            
            # Set up logging with UTF-8 encoding
            for handler in logging.root.handlers:
                if isinstance(handler, logging.StreamHandler):
                    handler.setStream(open(os.devnull, 'w'))  # Close existing handler
            
            # Create new handler with UTF-8 encoding
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            logging.root.addHandler(console_handler)

            # Use multiple selectors with shorter timeout
            found = False
            found_elements = []
            
            for selector in selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        if selector in ["article[data-testid='search-result']", "div[data-testid='advertCard']"]:
                            found_elements = elements
                        else:
                            # If we found a container, look for listing elements within it
                            found_elements = elements[0].find_elements(By.CSS_SELECTOR, "article[data-testid='search-result']")
                            if not found_elements:
                                found_elements = elements[0].find_elements(By.CSS_SELECTOR, "div[data-testid='advertCard']")
                        
                        if found_elements:
                            found = True
                            logging.info(f"Found {len(found_elements)} results using selector: {selector}")
                            break  # Exit the loop since we found results
                except Exception as e:
                    logging.warning(f"Failed to find results using selector '{selector}': {str(e)}")
                    continue  # Try next selector

            if not found:
                # Take a screenshot for debugging
                try:
                    screenshot_dir = Path("output/debug_screenshots")
                    screenshot_dir.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    screenshot_path = screenshot_dir / f"no_results_{timestamp}.png"
                    driver.save_screenshot(str(screenshot_path))
                    logging.info(f"Saved debug screenshot to {screenshot_path}")
                except Exception as e:
                    logging.error(f"Failed to save debug screenshot: {e}")
                
                logging.error("Could not find any results container")
                continue

            # If we found elements, use those instead of searching again
            listings = found_elements

            # Handle cookie consent (AutoTrader specific + fallbacks)
            try:
                cookie_selectors = [
                    "#onetrust-accept-btn-handler",             # AutoTrader / OneTrust
                    "button[data-testid='sp_choice_type_11']",  # Source Point
                    "button.sp_choice_type_11",
                    "button[title='Accept All']",
                    "button.accept-all-cookies",
                    "#consent_prompt_submit",
                    ".cookie-notice__accept-button"
                ]
                
                for selector in cookie_selectors:
                    try:
                        cookie_button = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                        )
                        cookie_button.click()
                        logging.info(f"Accepted cookies using selector: {selector}")
                        time.sleep(2)
                        break
                    except:
                        continue
            except Exception as e:
                logging.debug(f"Cookie handling error (non-critical): {str(e)}")

            # Delay to mimic human behavior
            time.sleep(2 + random.random() * 3)
            
            # Scroll down to trigger lazy loading
            for _ in range(4):
                scroll_amount = random.randint(300, 800)
                driver.execute_script(f"window.scrollBy(0, {scroll_amount})")
                time.sleep(1 + random.random())
            
            # Scroll back to top
            driver.execute_script("window.scrollTo(0, 0)")
            time.sleep(1)

            return True

        except Exception as e:
            if attempt < max_retries - 1:
                logging.warning(f"Failed to load page (attempt {attempt + 1}/{max_retries}): {str(e)}")
                time.sleep(5 * (attempt + 1))  # Backoff
                try:
                    driver.refresh()
                    time.sleep(3)
                except:
                    pass
            else:
                logging.error(f"Failed to load page after {max_retries} attempts: {str(e)}")
                return False
    
    return False


def scrape_autotrader(cars, criteria):
    """
    Scrapes car listings from AutoTrader UK based on given criteria.

    Args:
        cars (list): List of dictionaries containing car make and model to search for.
                    Format: [{"make": "Brand", "model": "Model"}, ...]
        criteria (dict): Search criteria including:
                        - postcode: UK postcode for location-based search
                        - radius: Search radius in miles
                        - year_from: Earliest year to search from (optional)
                        - year_to: Latest year to search to (optional)
                        - price_from: Minimum price (optional)
                        - price_to: Maximum price (optional)

    Returns:
        list: List of dictionaries containing car details including:
              - name: Full car name (make + model)
              - price: Listed price
              - year: Registration year
              - mileage: Total mileage
              - transmission: Manual/Automatic
              - fuel: Fuel type
              - engine: Engine size
              - owners: Number of previous owners
              - location: Dealer location
              - distance: Distance from search postcode
              - link: URL to full listing
    """
    start_time = time.time()
    logging.info("Starting AutoTrader scraper")
    
    # Initialize WebDriver with version checking
    driver = initialize_webdriver()
    data = []

    try:
        # Set reasonable timeouts
        driver.set_page_load_timeout(30)  # Increase timeout for initial load
        driver.set_script_timeout(10)
        
        for car_idx, car in enumerate(cars, 1):
            car_start_time = time.time()
            logging.info(f"\nProcessing car {car_idx}/{len(cars)}: {car['make']} {car['model']}")

            # Add random delay between searches to appear more human-like
            time.sleep(2 + random.random() * 3)
            
            # Construct the URL with proper encoding
            make = urllib.parse.quote(car['make'])
            model = urllib.parse.quote(car['model'])
            postcode = urllib.parse.quote(criteria['postcode'])
            
            url = "https://www.autotrader.co.uk/car-search?" + \
                "advertising-location=at_cars&" + \
                f"make={make}&" + \
                f"model={model}&" + \
                f"postcode={postcode}&" + \
                f"radius={criteria['radius']}&" + \
                "sort=price" 
            
            logging.info(f"Target URL: {url}")
            
            try:
                # First check if we can access the search page directly
                if not load_page_with_retry(driver, url):
                    logging.error("Failed to load search page directly")
                    continue

                # Get all the listings using the primary selector
                listings = driver.find_elements(By.CSS_SELECTOR, "article[data-testid='search-result']")
                if not listings:
                    # Try alternative selector
                    listings = driver.find_elements(By.CSS_SELECTOR, "div[data-testid='advertCard']")
                    
                if not listings:
                    logging.warning("No listings found")
                    continue
                    
                logging.info(f"Found {len(listings)} listings")
                
                # Process each listing
                for idx, listing in enumerate(listings, 1):
                    try:
                        details = {
                            "name": car['make'] + " " + car['model'],
                            "price": None,
                            "year": None,
                            "mileage": None,
                            "mileage_comparison": None,
                            "transmission": None,
                            "fuel": None,
                            "engine": None,
                            "subtitle": None,
                            "location": None,
                            "distance": None,
                            "link": None,
                            "body_type": None,
                            "doors": None,
                            "seats": None,
                            "service_history": None,
                            "emission_class": None,
                            "number_of_keys": None,
                            "owners": None,
                            "features": None
                        }
                        
                        logging.info(f"\nProcessing listing {idx}:")
                        logging.info("-" * 30)
                        
                        # Get link and title
                        try:
                            link_elem = listing.find_element(By.CSS_SELECTOR, "a[data-testid='search-listing-title']")
                            if link_elem:
                                link = link_elem.get_attribute("href")
                                details["link"] = link
                                logging.info(f"Link: {link}")
                                
                                # Get the title text which includes the model variant
                                title_text = link_elem.text.strip()
                                logging.info(f"Title: {title_text}")
                        except Exception as e:
                            logging.warning(f"Link/title extraction failed: {str(e)}")
                        
                        # Get price
                        try:
                            price_elem = listing.find_element(By.CSS_SELECTOR, ".at__sc-1n64n0d-8.at__sc-u4ap7c-15")
                            if price_elem:
                                price_text = price_elem.text.strip()
                                price_match = re.search(r'£[\d,]+', price_text)
                                if price_match:
                                    details["price"] = price_match.group(0)
                                    logging.info(f"Price: {details['price']}")
                        except Exception as e:
                            logging.warning(f"Price extraction failed: {str(e)}")
                        
                        # Get year and mileage from badges
                        try:
                            badges = listing.find_elements(By.CSS_SELECTOR, "ul[data-testid='badges-container'] li")
                            for badge in badges:
                                try:
                                    badge_text = badge.text.strip().lower()
                                    logging.info(f"Processing badge: {badge_text}")
                                    
                                    # Mileage
                                    if 'miles' in badge_text:
                                        mileage_match = re.search(r'([\d,]+)\s*miles?', badge_text)
                                        if mileage_match:
                                            details["mileage"] = mileage_match.group(1)
                                            logging.info(f"Mileage: {details['mileage']}")
                                    
                                    # Year
                                    elif 'reg' in badge_text:
                                        year_match = re.search(r'(20\d{2}|19\d{2})', badge_text)
                                        if year_match:
                                            details["year"] = year_match.group(1)
                                            logging.info(f"Year: {details['year']}")
                                except Exception as e:
                                    logging.warning(f"Error processing badge: {str(e)}")
                        except Exception as e:
                            logging.warning(f"Badges extraction failed: {str(e)}")
                        
                        # Get location and distance
                        try:
                            location_elem = listing.find_element(By.CSS_SELECTOR, "[data-testid='search-listing-location'] .at__sc-m0lx8i-1")
                            if location_elem:
                                location_text = location_elem.text.strip()
                                location_match = re.search(r'(.*?)\s*\((\d+(?:\.\d+)?)\s*miles?\)', location_text)
                                if location_match:
                                    details["location"] = location_match.group(1).strip()
                                    details["distance"] = location_match.group(2)
                                    logging.info(f"Location: {details['location']}, Distance: {details['distance']}")
                        except Exception as e:
                            logging.warning(f"Location extraction failed: {str(e)}")
                        
                        # Get additional details from subtitle
                        try:
                            subtitle_elem = listing.find_element(By.CSS_SELECTOR, "[data-testid='search-listing-subtitle']")
                            if subtitle_elem:
                                subtitle_text = subtitle_elem.text.strip()
                                details["subtitle"] = subtitle_text
                                logging.info(f"Subtitle: {subtitle_text}")
                                
                                subtitle_lower = subtitle_text.lower()
                                
                                # Engine size
                                engine_match = re.search(r'(\d+\.\d+)', subtitle_lower)
                                if engine_match:
                                    details["engine"] = engine_match.group(1) + "L"
                                    logging.info(f"Engine: {details['engine']}")
                                
                                # Transmission
                                if 'manual' in subtitle_lower:
                                    details["transmission"] = "Manual"
                                    logging.info("Found Manual transmission")
                                elif 'auto' in subtitle_lower:
                                    details["transmission"] = "Automatic"
                                    logging.info("Found Automatic transmission")
                                
                                # Fuel type
                                fuel_patterns = {
                                    'diesel': ['diesel', 'tdi', 'td4', 'td5', 'td6', 'cdi', 'dci', 'hdi', 'd4d', 
                                              ' td ', ' sd ', 'sd4', 'sd6'],  # Added space-padded patterns
                                    'petrol': ['petrol', 'tsi', 'tfsi', 'vti', 'fsi', 'gti', 'mpi', 'vvti',
                                             ' si ', ' ti '],  # Added space-padded patterns
                                    'hybrid': ['hybrid', 'phev', 'mhev', 'hev'],
                                    'electric': ['electric', 'ev', 'bev']
                                }
                                
                                # Helper function to check for fuel type
                                def check_fuel_type(text):
                                    text = f" {text.lower()} "  # Add spaces to help with whole word matching
                                    for fuel_type, patterns in fuel_patterns.items():
                                        if any(pattern in text for pattern in patterns):
                                            return fuel_type.title()
                                    return None
                                
                                # Try to find fuel type in subtitle first
                                if subtitle_text:
                                    details["fuel"] = check_fuel_type(subtitle_text)
                                    if details["fuel"]:
                                        logging.info(f"Fuel type (from subtitle): {details['fuel']}")
                                
                                # If not found in subtitle, try title
                                if not details["fuel"] and title_text:
                                    details["fuel"] = check_fuel_type(title_text)
                                    if details["fuel"]:
                                        logging.info(f"Fuel type (from title): {details['fuel']}")
                                
                                # If still not found, try name
                                if not details["fuel"] and details["name"]:
                                    details["fuel"] = check_fuel_type(details["name"])
                                    if details["fuel"]:
                                        logging.info(f"Fuel type (from name): {details['fuel']}")
                        except Exception as e:
                            logging.warning(f"Subtitle extraction failed: {str(e)}")
                        
                        # Extract overview information
                        try:
                            # Get overview text
                            overview_elem = listing.find_element(By.CSS_SELECTOR, "[data-testid='overview']")
                            if overview_elem:
                                overview_text = overview_elem.text.strip()
                                # Extract features from overview (comma separated)
                                features = [f.strip() for f in overview_text.split(',')]
                                details["features"] = ','.join(features)
                                logging.info(f"Features: {details['features']}")
                                
                                # Extract number of keys if present
                                keys_match = re.search(r'(\d+)\s*KEYS', overview_text, re.IGNORECASE)
                                if keys_match:
                                    details["number_of_keys"] = keys_match.group(1)
                                    logging.info(f"Number of keys: {details['number_of_keys']}")
                            
                            # Get mileage comparison
                            mileage_comp_elem = listing.find_element(By.CSS_SELECTOR, "[data-testid='mileage-comparison']")
                            if mileage_comp_elem:
                                comp_text = mileage_comp_elem.text.strip()
                                details["mileage_comparison"] = comp_text
                                logging.info(f"Mileage comparison: {comp_text}")
                            
                            # Get number of owners
                            owners_elem = listing.find_element(By.CSS_SELECTOR, "[data-testid='owners']")
                            if owners_elem:
                                owners_text = owners_elem.text.strip()
                                owners_match = re.search(r'(\d+)\s*owners?', owners_text, re.IGNORECASE)
                                if owners_match:
                                    details["owners"] = owners_match.group(1)
                                    logging.info(f"Number of owners: {details['owners']}")
                                    
                        except Exception as e:
                            logging.warning(f"Error extracting overview information: {str(e)}")
                        
                        # Summary of extracted data
                        logging.info("\nExtracted Data Summary:")
                        logging.info("-" * 30)
                        for key, value in details.items():
                            if value is not None:
                                logging.info(f"{key}: {value}")
                            else:
                                logging.warning(f"Missing: {key}")
                        
                        # Only add if we have the minimum required data
                        if all(details[k] is not None for k in ["price", "year", "mileage"]):
                            data.append(details)
                            logging.info("Successfully added listing")
                        else:
                            logging.warning("Skipping listing - missing required data")
                        
                        logging.info("-" * 30 + "\n")
                        
                    except Exception as e:
                        logging.error(f"Error processing listing {idx}: {str(e)}")
                        continue

            except Exception as e:
                logging.error(f"Error processing page: {str(e)}")
                continue

    finally:
        driver.quit()
        total_time = time.time() - start_time
        logging.info(f"\nScraping completed. Total time: {total_time:.1f} seconds")
        logging.info(f"Total cars found: {len(data)}")

    return data


def output_data_to_excel(data, criteria):
    """
    Processes scraped data and outputs it to an Excel file with formatting.

    The function performs the following operations:
    1. Creates an output directory if it doesn't exist
    2. Cleans and formats the data (removes £ signs, commas, etc.)
    3. Calculates additional metrics (miles per year)
    4. Applies conditional formatting to highlight good/bad values
    5. Saves the file with retry logic in case of file access issues

    Args:
        data (list): List of dictionaries containing car details from scrape_autotrader()
        criteria (dict): Search criteria used, affects price filtering

    Output:
        Creates an Excel file at output/cars.xlsx with the following columns:
        - Basic info: name, link, price, year
        - Usage info: mileage, miles_pa (per annum), owners
        - Location info: distance, location
        - Technical info: engine, transmission, fuel
    """
    start_time = time.time()
    logging.info("\nStarting Excel output processing")

    if not data:
        logging.warning("No data to write to Excel.")
        return

    # Create output directory if it doesn't exist
    os.makedirs("output", exist_ok=True)
    
    df = pd.DataFrame(data)
    logging.info(f"Processing {len(df)} records")

    # Clean up price data - remove currency symbol and commas
    df["price"] = df["price"].str.replace("£", "").str.replace(",", "")
    df["price"] = pd.to_numeric(df["price"], errors="coerce").astype("Int64")

    # Clean up year data - remove registration info
    df["year"] = df["year"].str.replace(r"\s(\(\d\d reg\))", "", regex=True)
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")

    # Clean up mileage data
    df["mileage"] = df["mileage"].str.replace(",", "").str.replace(" miles", "")
    df["mileage"] = pd.to_numeric(df["mileage"], errors="coerce").astype("Int64")

    # Calculate miles per year
    now = datetime.datetime.now()
    df["miles_pa"] = df["mileage"] / (now.year - df["year"])
    df["miles_pa"] = df["miles_pa"].fillna(0)
    df["miles_pa"] = df["miles_pa"].astype(int)

    # Handle missing values for distance
    df["distance"] = df["distance"].fillna("-1") 
    df["distance"] = df["distance"].astype(int)

    # Organize columns in logical groups
    df = df[[
        "name",
        "link",
        "subtitle",
        "features",
        "price",
        "year",
        "mileage",
        "mileage_comparison",
        "miles_pa",
        "owners",
        "number_of_keys",
        "body_type",
        "doors",
        "seats",
        "service_history",
        "distance",
        "location",
        "engine",
        "transmission",
        "fuel",
        "emission_class"
    ]]

    # Apply price filter if specified
    if criteria["price_to"]:
        df = df[df["price"] < int(criteria["price_to"])]

    df = df.sort_values(by="distance", ascending=True)

    output_path = os.path.join("output", "cars.xlsx")
    logging.info(f"Writing to Excel file: {output_path}")
    
    # Try to write the file with retry logic
    max_retries = 3
    for attempt in range(max_retries):
        try:
            writer = pd.ExcelWriter(output_path, engine="xlsxwriter")
            df.to_excel(writer, sheet_name="Cars", index=False)
            workbook = writer.book
            worksheet = writer.sheets["Cars"]

            # Apply conditional formatting:
            # - Green is good for low prices, newer years, low mileage
            # - Red is bad for high prices, older years, high mileage
            worksheet.conditional_format("C2:C1000", {
                'type':      '3_color_scale',
                'min_color': '#63be7b',  # Green for good (low price)
                'mid_color': '#ffdc81',  # Yellow for average
                'max_color': '#f96a6c'   # Red for bad (high price)
            })

            worksheet.conditional_format("D2:D1000", {
                'type':      '3_color_scale',
                'min_color': '#f96a6c',
                'mid_color': '#ffdc81',
                'max_color': '#63be7b'
            })

            worksheet.conditional_format("E2:E1000", {
                'type':      '3_color_scale',
                'min_color': '#63be7b',
                'mid_color': '#ffdc81',
                'max_color': '#f96a6c'
            })

            worksheet.conditional_format("F2:F1000", {
                'type':      '3_color_scale',
                'min_color': '#63be7b',
                'mid_color': '#ffdc81',
                'max_color': '#f96a6c'
            })

            writer.close()
            logging.info(f"Successfully saved to {output_path}")
            total_time = time.time() - start_time
            logging.info(f"Excel processing completed in {total_time:.1f} seconds")
            break
        except PermissionError:
            if attempt < max_retries - 1:
                logging.warning(f"Excel file is open. Retrying in 5 seconds... (Attempt {attempt + 1}/{max_retries})")
                time.sleep(5)
            else:
                logging.error("Could not save Excel file. Please close it and try again.")
                return


if __name__ == "__main__":
    # Set up logging before anything else
    setup_logging()
    
    # Example search criteria and car list
    # Modify these values or load them from a config file
    criteria = {
        "postcode": "cv31 3af",  # Center of search location
        "radius": "5",          # Search radius in miles
        "year_from": "",         # Optional: Earliest year to consider
        "year_to": "",          # Optional: Latest year to consider
        "price_from": "",       # Optional: Minimum price
        "price_to": "",         # Optional: Maximum price
    }

    cars = [
        {
            "make": "Land Rover",
            "model": "Discovery"
        }
        # Add more cars to search for as needed
    ]

    try:
        data = scrape_autotrader(cars, criteria)
        output_data_to_excel(data, criteria)
        # Use quotes around path to handle spaces
        os.system(f'start EXCEL.EXE "{os.path.abspath(os.path.join("output", "cars.xlsx"))}"')
    except Exception as e:
        logging.error(f"An error occurred: {str(e)}", exc_info=True)
