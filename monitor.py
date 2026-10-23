
import os
import json
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
    "flesh and blood", "battle spirits"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
}


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Mancano i segreti Telegram su GitHub.")

    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
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
        return set()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, list):
            return set(data)

        return set(data.get("products", []))
    except (json.JSONDecodeError, OSError):
        return set()


def save_state(products):
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(
            {"products": sorted(products)},
            file,
            ensure_ascii=False,
            indent=2,
        )


def is_tcg(title):
    return any(word in title.lower() for word in KEYWORDS)


def get_products(url, category):
    products = {}

    for page in range(1, 41):
        page_url = url if page == 1 else f"{url}?product-page={page}"

        response = requests.get(page_url, headers=HEADERS, timeout=25)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select(
            "li.product, .product-small, .product-item, "
            ".wc-block-grid__product"
        )

        if not cards:
            break

        for card in cards:
            title_element = card.select_one(
                ".woocommerce-loop-product__title, .product-title, h2, h3"
            )
            link = card.select_one("a[href]")

            if not title_element or not link:
                continue

            title = title_element.get_text(" ", strip=True)
            product_url = urljoin(BASE_URL, link.get("href", ""))

            if not title or not is_tcg(title):
                continue

            price_element = card.select_one(
                ".price, .woocommerce-Price-amount"
            )
            price = (
                price_element.get_text(" ", strip=True)
                if price_element else "Prezzo da verificare"
            )

            products[product_url] = {
                "title": title,
                "url": product_url,
                "price": price,
                "category": category,
            }

        time.sleep(1)

    return products


def main():
    old_products = load_state()
    current_products = {}

    for category, url in SOURCES:
        print(f"Controllo {category}...")
        try:
            current_products.update(get_products(url, category))
        except requests.RequestException as error:
            print(f"Errore durante il controllo: {error}")
            raise

    if not current_products:
        raise RuntimeError(
            "Nessun prodotto trovato: storico non modificato."
        )

    current_urls = set(current_products)

    # Prima scansione: registra i prodotti senza inviare notifiche singole.
    if not old_products:
        save_state(current_urls)
        send_telegram(
            "✅ Monitor CarteMagic attivo!\n"
            f"Registrati {len(current_urls)} prodotti TCG.\n"
            "Da ora ti avviserò solo delle novità, "
            "con un unico messaggio riepilogativo."
        )
        return

    new_urls = current_urls - old_products

    # Salva i prodotti prima dell'invio per evitare duplicati ai controlli successivi.
    save_state(old_products | current_urls)

    if not new_urls:
        print("Nessuna novità.")
        return

    messages = ["🆕 NOVITÀ TCG SU CARTEMAGIC\n"]

    for product_url in sorted(new_urls):
        product = current_products[product_url]
        messages.append(
            f"📦 {product['title']}\n"
            f"🏷️ {product['category']}\n"
            f"💶 {product['price']}\n"
            f"🔗 {product['url']}"
        )

    message = "\n\n".join(messages)

    # Telegram limita i messaggi a circa 4096 caratteri.
    chunks = []
    while len(message) > 3900:
        split_at = message.rfind("\n\n", 0, 3900)
        if split_at < 1:
            split_at = 3900
        chunks.append(message[:split_at])
        message = message[split_at:].lstrip()
    if message:
        chunks.append(message)

    for chunk in chunks:
        send_telegram(chunk)
        time.sleep(1)

    print(f"Novità rilevate: {len(new_urls)}")


if __name__ == "__main__":
    main()
