
import os
import json
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://www.cartemagic.com"
SOURCES = [
    ("Novità TCG", "https://www.cartemagic.com/carte-collezionabili/"),
    ("Preordini TCG", "https://www.cartemagic.com/categoria/preordini/"),
]

STATE_FILE = "seen_products.json"
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

KEYWORDS = [
    "pokemon", "one piece", "magic", "yu-gi-oh", "yugioh",
    "lorcana", "dragon ball", "digimon", "riftbound",
    "union arena", "star wars unlimited", "final fantasy",
    "fab", "flesh and blood", "battle spirits"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
}


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Errore: mancano i segreti Telegram.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    response.raise_for_status()


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"products": []}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, list):
            return {"products": data}

        return data
    except (json.JSONDecodeError, OSError):
        return {"products": []}


def save_state(products):
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(
            {"products": sorted(products)},
            file,
            ensure_ascii=False,
            indent=2,
        )


def is_tcg(title):
    title_lower = title.lower()
    return any(keyword in title_lower for keyword in KEYWORDS)


def get_products(url):
    products = {}

    for page in range(1, 41):
        page_url = url if page == 1 else f"{url}?product-page={page}"

        try:
            response = requests.get(
                page_url,
                headers=HEADERS,
                timeout=25,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            print(f"Errore nel caricamento {page_url}: {error}")
            break

        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select(
            "li.product, .product-small, .product-item, "
            ".wc-block-grid__product"
        )

        if not cards:
            if page == 1:
                print(f"Nessun prodotto riconosciuto in {url}")
            break

        found_on_page = 0

        for card in cards:
            link = card.select_one(
                "a.woocommerce-LoopProduct-link, "
                "a.product-image-link, a[href]"
            )
            title_element = card.select_one(
                ".woocommerce-loop-product__title, "
                ".product-title, h2, h3"
            )

            if not link or not title_element:
                continue

            title = title_element.get_text(" ", strip=True)
            product_url = urljoin(BASE_URL, link.get("href", ""))

            if not title or not product_url.startswith("http"):
                continue

            if not is_tcg(title):
                continue

            price_element = card.select_one(
                ".price, .woocommerce-Price-amount"
            )
            price = (
                price_element.get_text(" ", strip=True)
                if price_element
                else "Prezzo da verificare"
            )

            products[product_url] = {
                "title": title,
                "url": product_url,
                "price": price,
            }
            found_on_page += 1

        print(f"Pagina {page}: {found_on_page} prodotti TCG")

        if page > 1 and found_on_page == 0:
            break

        time.sleep(1)

    return products


def main():
    old_state = load_state()
    old_products = set(old_state.get("products", []))
    current_products = {}

    for category, url in SOURCES:
        print(f"Controllo: {category}")
        found = get_products(url)

        for product_url, product in found.items():
            product["category"] = category
            current_products[product_url] = product

    if not current_products:
        print("Nessun prodotto trovato. Non modifico lo stato.")
        return

    new_urls = set(current_products) - old_products

    if not old_products:
        save_state(current_products.keys())
        send_telegram(
            "Monitor CarteMagic avviato!\n"
            f"Prodotti TCG riconosciuti: {len(current_products)}.\n"
            "Questa è la scansione iniziale: ti avviserò "
            "quando rileverò nuovi prodotti."
        )
        print("Prima scansione completata.")
        return

    for product_url in sorted(new_urls):
        product = current_products[product_url]
        message = (
            f"🆕 NUOVO PRODOTTO TCG\n\n"
            f"📦 {product['title']}\n"
            f"🏷️ {product['category']}\n"
            f"💶 {product['price']}\n\n"
            f"🔗 {product['url']}"
        )
        send_telegram(message)
        time.sleep(1)

    save_state(old_products | set(current_products.keys()))
    print(f"Controllo completato. Nuovi prodotti: {len(new_urls)}.")


if __name__ == "__main__":
    main()
