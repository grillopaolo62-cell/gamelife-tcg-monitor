
import os
import json
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://www.cartemagic.com"
SOURCES = [
    ("Catalogo TCG", "https://www.cartemagic.com/carte-collezionabili/"),
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


def telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Configurazione Telegram mancante.")

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
        return None

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, list):
            return set(data)
        return set(data.get("products", []))
    except (json.JSONDecodeError, OSError):
        return None


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


def scan(url, category):
    found = {}

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
            title_el = card.select_one(
                ".woocommerce-loop-product__title, .product-title, h2, h3"
            )
            link = card.select_one("a[href]")
            if not title_el or not link:
                continue

            title = title_el.get_text(" ", strip=True)
            product_url = urljoin(BASE_URL, link.get("href", ""))

            if not title or not is_tcg(title):
                continue

            price_el = card.select_one(
                ".price, .woocommerce-Price-amount"
            )
            price = (
                price_el.get_text(" ", strip=True)
                if price_el else "Prezzo da verificare"
            )

            found[product_url] = {
                "title": title,
                "url": product_url,
                "price": price,
                "category": category,
            }

        time.sleep(1)

    return found


def main():
    previous = load_state()
    current = {}

    for category, url in SOURCES:
        print(f"Controllo {category}")
        current.update(scan(url, category))

    if not current:
        raise RuntimeError(
            "Nessun prodotto trovato: controllo interrotto senza modificare lo storico."
        )

    current_urls = set(current)

    # Se manca lo storico, inizializza senza notificare i prodotti esistenti.
    if previous is None:
        save_state(current_urls)
        telegram(
            "✅ Monitor CarteMagic configurato.\n"
            f"Registrati {len(current_urls)} prodotti TCG.\n"
            "Da ora riceverai avvisi solo per le novità rilevate."
        )
        return

    new_urls = current_urls - previous
    save_state(previous | current_urls)

    if not new_urls:
        print("Nessuna novità.")
        return

    entries = []
    for url in sorted(new_urls):
        p = current[url]
        entries.append(
            f"📦 {p['title']}\n"
            f"🏷️ {p['category']}\n"
            f"💶 {p['price']}\n"
            f"🔗 {p['url']}"
        )

    # Un solo messaggio, diviso solo se supera il limite di Telegram.
    message = "🆕 NOVITÀ TCG SU CARTEMAGIC\n\n" + "\n\n".join(entries)
    chunks = []

    while len(message) > 3900:
        split_at = message.rfind("\n\n", 0, 3900)
        if split_at <= 0:
            split_at = 3900
        chunks.append(message[:split_at])
        message = message[split_at:].lstrip()

    if message:
        chunks.append(message)

    for chunk in chunks:
        telegram(chunk)
        time.sleep(1)

    print(f"Nuovi prodotti: {len(new_urls)}")


if __name__ == "__main__":
    main()
