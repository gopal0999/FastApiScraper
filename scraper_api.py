from fastapi import FastAPI, HTTPException, Depends
import requests
from bs4 import BeautifulSoup
import json
import os
import redis
from typing import Optional, List, Dict
from tenacity import retry, stop_after_attempt, wait_fixed

# FastAPI app
app = FastAPI()

# Static API Token for Authentication
API_TOKEN = "secure_token_123"

# Redis connection for caching
redis_client = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

def authenticate(token: str):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

# --- Storage Strategy ---
class StorageStrategy:
    def save(self, data: List[Dict]):
        raise NotImplementedError

    def load(self) -> List[Dict]:
        raise NotImplementedError

class JSONStorage(StorageStrategy):
    FILE_PATH = "scraped_data.json"

    def save(self, data: List[Dict]):
        with open(self.FILE_PATH, "w") as file:
            json.dump(data, file, indent=4)

    def load(self) -> List[Dict]:
        if os.path.exists(self.FILE_PATH):
            with open(self.FILE_PATH, "r") as file:
                return json.load(file)
        return []

class InMemoryStorage(StorageStrategy):
    def __init__(self):
        self.data = []

    def save(self, data: List[Dict]):
        self.data = data

    def load(self) -> List[Dict]:
        return self.data

# --- Notification Strategy ---
class NotificationStrategy:
    def send(self, message: str):
        raise NotImplementedError

class ConsoleNotification(NotificationStrategy):
    def send(self, message: str):
        print(message)

# --- Scraper Class ---
class Scraper:
    def __init__(self, page_limit: int, proxy: Optional[str] = None):
        self.base_url = "https://dentalstall.com/shop/page/"
        self.page_limit = page_limit
        self.session = requests.Session()
        self.proxies = {"http": proxy, "https": proxy} if proxy else None

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def scrape_page(self, page_number):
        url = f"{self.base_url}{page_number}/"
        try:
            response = self.session.get(url, proxies=self.proxies, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
            return None

    def parse_page(self, html):
        soup = BeautifulSoup(html, "html.parser")
        products = []
        shop_content = soup.find("div", id="mf-shop-content")

        if shop_content:
            for ul in shop_content.find_all("ul"):
                for product in ul.find_all("li", class_=lambda x: x and 'product' in x):
                    product_item = {"product_title": "", "product_price": "", "path_to_image": ""}
                        
                    product_inner = product.find("div", class_="product-inner clearfix")
                    
                    if product_inner:
                        product_inner_name_price_div = product_inner.find("div", class_="mf-product-details")
                        if product_inner_name_price_div:
                            product_inner_name = product_inner_name_price_div.find("div", class_="mf-product-content").find("h2").find("a").get_text(strip=True)
                            product_item["product_title"] = product_inner_name
                            
                            price_box = product_inner_name_price_div.find("div", class_="mf-product-price-box")
                            ins_tag = price_box.find("ins")
                            if ins_tag:
                                price = ins_tag.get_text(strip=True)
                            else:
                                bdi_tag = price_box.find("span", class_="woocommerce-Price-amount amount")
                                price = bdi_tag.get_text(strip=True) if bdi_tag else "N/A"
                            product_item["product_price"] = price
                            
                        img_tag = product_inner.find("div", class_="mf-product-thumbnail").find("a").find("img")
                        img_src = img_tag["data-lazy-src"] if img_tag and img_tag.has_attr("data-lazy-src") else None
                        product_item["path_to_image"] = img_src
                        products.append(product_item)
        return products

    def scrape(self):
        all_products = []
        for page in range(1, self.page_limit + 1):
            html = self.scrape_page(page)
            if html:
                all_products.extend(self.parse_page(html))
        return all_products

# --- Scraping Controller ---
class ScrapingController:
    def __init__(self, storage: StorageStrategy, notification: NotificationStrategy):
        self.storage = storage
        self.notification = notification

    def scrape_and_store(self, page_limit: int, proxy: Optional[str] = None):
        scraper = Scraper(page_limit, proxy)
        scraped_data = scraper.scrape()

        existing_data = self.storage.load()
        updated_count = 0

        for product in scraped_data:
            cache_key = f"{product['product_title']}_price"
            cached_price = redis_client.get(cache_key)

            if cached_price is None or cached_price != product["product_price"]:
                redis_client.set(cache_key, product["product_price"])
                updated_count += 1

        if updated_count > 0:
            self.storage.save(scraped_data)

        self.notification.send(f"Scraped {len(scraped_data)} products. Updated {updated_count} products.")
        return {"message": f"Scraped {len(scraped_data)} products. Updated {updated_count} products."}

# --- API Route ---
@app.post("/scrape/")
def start_scraping(page_limit: int, proxy: Optional[str] = None, token: str = Depends(authenticate)):
    storage = JSONStorage()
    notification = ConsoleNotification()
    controller = ScrapingController(storage, notification)
    return controller.scrape_and_store(page_limit, proxy)
