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

import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver  
from selenium.webdriver.common.keys import Keys  
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

criteria = {
    "postcode": "cv31 3af",
    "radius": "50",
    "year_from": "",
    "year_to": "",
    "price_from": "",
    "price_to": "",
}


cars = [
    {
         "make": "Land Rover",
         "model": "Discovery"
    }
]


def scrape_autotrader(cars, criteria):
    chrome_options = Options()
    chrome_options.add_argument("_tt_enable_cookie=1")
    # chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(options = chrome_options)
    data = []

    for car in cars:

        # Example URL: 
        # https://www.autotrader.co.uk/car-search?advertising-location=at_cars&include-delivery-option
        # =on&make=Honda&model=Jazz&postcode=LS12AD&radius=10&sort=relevance&year-from=2011&year-to=2015
        if ' ' in car['make']: car['make'] = car['make'].replace(' ', '%20')
        if ' ' in car['model']: car['model'] = car['model'].replace(' ', '%20')
        if ' ' in criteria['postcode']: criteria['postcode'] = criteria['postcode'].replace(' ', '%20')
        url = "https://www.autotrader.co.uk/car-search?" + \
            "advertising-location=at_cars&" + \
            f"make={car['make']}&" + \
            f"model={car['model']}&" + \
            f"postcode={criteria['postcode']}&" + \
            f"radius={criteria['radius']}&" + \
            "sort=price" 
        print(f"Looking for : {url}")
        driver.get(url)

        print(f"Searching for {car['make']} {car['model']}...")

        time.sleep(5) 

        source = driver.page_source
        content = BeautifulSoup(source, "html.parser")

        # Find the paragraph containing the page information
        page_info = content.find("p", string=re.compile(r'Page \d{1,2} of \d{1,2}'))

        # Extract the total number of pages using a capturing group
        if page_info:
            match = re.search(r'Page \d{1,2} of (\d{1,2})', page_info.text)
            if match:
                number_of_pages = int(match.group(1))
            else:
                print("No match found.")
        else:
            print("No page information found.")
            continue
        
        
        print(f"There are {number_of_pages} pages in total.")

        for i in range(int(number_of_pages)):
            driver.get(url + f"&page={str(i + 1)}")
            
            time.sleep(5)
            page_source = driver.page_source
            content = BeautifulSoup(page_source, "html.parser")

            articles = content.findAll("section", attrs={"data-testid": "trader-seller-listing"})

            print(f"Scraping page {str(i + 1)}...")

            for article in articles:
                details = {
                    "name": car['make'] + " " + car['model'],
                    "price": re.search(r"[£]\d+(\,\d{3})?", article.text).group(0),
                    "year": None,
                    "mileage": None,
                    "transmission": None,
                    "fuel": None,
                    "engine": None,
                    "owners": None,
                    "location": None,
                    "distance": None,
                    "link": article.find("a", {"href": re.compile(r'/car-details/')}).get("href")
                } 

                try:
                    seller_info = article.find("p", attrs={"data-testid": "search-listing-seller"}).text
                    location = seller_info.split("Dealer location")[1] 
                    details["location"] = location.split("(")[0]
                    details["distance"] = location.split("(")[1].replace(" mile)", "").replace(" miles)", "") 
                except:
                    print("Seller information not found.")

                specs_list = article.find("ul", attrs={"data-testid": "search-listing-specs"})
                for spec in specs_list:
                    if "reg" in spec.text:
                        details["year"] = spec.text

                    if "miles" in spec.text: 
                        details["mileage"] = spec.text

                    if spec.text in ["Manual", "Automatic"]: 
                        details["transmission"] = spec.text

                    if "." in spec.text and "L" in spec.text:
                        details["engine"] = spec.text

                    if spec.text in ["Petrol", "Diesel"]: 
                        details["fuel"] = spec.text

                    if "owner" in spec.text:
                        details["owners"] = spec.text[0]

                data.append(details)

            print(f"Page {str(i + 1)} scraped. ({len(articles)} articles)")
            time.sleep(5)

        print("\n\n")

    print(f"{len(data)} cars total found.")

    return data


def output_data_to_excel(data, criteria):
    df = pd.DataFrame(data)

    df["price"] = df["price"].str.replace("£", "").str.replace(",", "")
    df["price"] = pd.to_numeric(df["price"], errors="coerce").astype("Int64")

    df["year"] = df["year"].str.replace(r"\s(\(\d\d reg\))", "", regex=True)
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")

    df["mileage"] = df["mileage"].str.replace(",", "").str.replace(" miles", "")
    df["mileage"] = pd.to_numeric(df["mileage"], errors="coerce").astype("Int64")

    now = datetime.datetime.now()
    df["miles_pa"] = df["mileage"] / (now.year - df["year"])
    df["miles_pa"] = df["miles_pa"].fillna(0)
    df["miles_pa"] = df["miles_pa"].astype(int)

    df["owners"] = df["owners"].fillna("-1") 
    df["owners"] = df["owners"].astype(int)

    df["distance"] = df["distance"].fillna("-1") 
    df["distance"] = df["distance"].astype(int)

    df["link"] = "https://www.autotrader.co.uk" + df["link"] 

    df = df[[
        "name",
        "link",
        "price",
        "year",
        "mileage",
        "miles_pa",
        "owners",
        "distance",
        "location",
        "engine",
        "transmission",
        "fuel",
    ]]
    if criteria["price_to"]:
        df = df[df["price"] < int(criteria["price_to"])]

    df = df.sort_values(by="distance", ascending=True)

    writer = pd.ExcelWriter("cars.xlsx", engine="xlsxwriter")
    df.to_excel(writer, sheet_name="Cars", index=False)
    workbook = writer.book
    worksheet = writer.sheets["Cars"]

    worksheet.conditional_format("C2:C1000", {
        'type':      '3_color_scale',
        'min_color': '#63be7b',
        'mid_color': '#ffdc81',
        'max_color': '#f96a6c'
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
    print("Output saved to current directory as 'cars.xlsx'.")


if __name__ == "__main__":
    data = scrape_autotrader(cars, criteria)
    output_data_to_excel(data, criteria)

    os.system("start EXCEL.EXE cars.xlsx")
