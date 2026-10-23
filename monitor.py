
import os
import json
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.cartemagic.com"
STATE_FILE = "seen_products.json"
BASELINE_FILE = ".baseline_initialized"

SOURCES = [
    (
        f"{BASE_URL}/carte-collezionabili/",
        "Catalogo TCG",
    ),
    (
        f"{BASE_URL}/categoria/preordini/",
        "Preordini TCG",
    ),
]

KEYWORDS = [
    "pokemon",
    "one piece",
    "magic",
    "yu-gi-oh",
    "yugioh",
    "lorcana",
    "dragon ball",
    "digimon",
    "riftbound",
    "union arena",
    "star wars unlimited",
    "final fantasy",
    "flesh and blood",
    "battle spirits",
    "gundam",
    "palworld",
    "battle spirits saga",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}

MAX_PAGES = 40
REQUEST_TIMEOUT = 20


def load_state():
    if not os.path.exists(STATE_FILE):
        return None

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, dict):
            products = data.get("products")

            if isinstance(products, list):
                return {
                    url
                    for url in products
                    if isinstance(url, str)
                }

        return None

    except (OSError, json.JSONDecodeError):
        return None


def save_state(urls):
    data = {
        "site": "cartemagic.com",
        "products": sorted(urls),
    }

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def matches_keywords(title, url):
    text = f"{title} {url}".lower()

    return any(keyword in text for keyword in KEYWORDS)


def get_product_cards(soup):
    cards = soup.select(
        "li.product, "
        "div.product.type-product, "
        "article.product"
    )

    if cards:
        return cards

    # Fallback per temi che usano una struttura diversa.
    links = soup.select('a[href*="/prodotto/"]')
    return links


def extract_product(card, page_url, category):
    link = card.select_one('a[href*="/prodotto/"]')

    if link is None and getattr(card, "name", None) == "a":
        link = card

    if link is None:
        return None

    product_url = urljoin(page_url, link.get("href", ""))

    if "/prodotto/" not in product_url:
        return None

    title_element = (
        card.select_one(
            ".woocommerce-loop-product__title, "
            ".product-title, h2, h3"
        )
    )

    if title_element:
        title = title_element.get_text(" ", strip=True)
    else:
        title = link.get_text(" ", strip=True)

    if not title:
        title = product_url.rstrip("/").split("/")[-1]
        title = title.replace("-", " ")

    if not matches_keywords(title, product_url):
        return None

    price_element = card.select_one(
        ".price, .woocommerce-Price-amount"
    )

    price = (
        price_element.get_text(" ", strip=True)
        if price_element
        else ""
    )

    return {
        "url": product_url.split("#")[0],
        "title": title,
        "price": price,
        "category": category,
    }


def scan(url, category):
    products = {}
    session = requests.Session()
    session.headers.update(HEADERS)

    for page_number in range(1, MAX_PAGES + 1):
        if page_number == 1:
            page_url = url
        else:
            separator = "&" if "?" in url else "?"
            page_url = (
                f"{url}{separator}product-page={page_number}"
            )

        try:
            response = session.get(
                page_url,
                timeout=REQUEST_TIMEOUT,
            )

        except requests.RequestException as error:
            print(
                f"Errore di connessione per {page_url}: {error}"
            )
            break

        if response.status_code == 403:
            print(
                f"ATTENZIONE: CarteMagic blocca {page_url} "
                f"(403). Salto questa sezione."
            )
            break

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        cards = get_product_cards(soup)

        if not cards:
            if page_number == 1:
                print(
                    f"Nessun prodotto riconosciuto in {category}."
                )
            break

        for card in cards:
            product = extract_product(
                card,
                page_url,
                category,
            )

            if product:
                products[product["url"]] = product

        print(
            f"{category}: pagina {page_number}, "
            f"{len(products)} prodotti TCG riconosciuti."
        )

        time.sleep(1)

    session.close()
    return products


def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError(
            "Mancano TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID "
            "nei Secrets di GitHub."
        )

    telegram_url = (
        f"https://api.telegram.org/bot{token}/sendMessage"
    )

    response = requests.post(
        telegram_url,
        data={
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=20,
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            "Telegram non ha accettato il messaggio."
        )


def send_new_products(products):
    header = "🆕 NOVITÀ TCG SU CARTEMAGIC\n\n"
    chunks = []
    current_message = header

    for product in products:
        entry = (
            f"📦 {product['title']}\n"
            f"📂 {product['category']}\n"
        )

        if product.get("price"):
            entry += f"🏷️ {product['price']}\n"

        entry += f"{product['url']}\n\n"

        if len(current_message) + len(entry) > 3500:
            chunks.append(current_message)
            current_message = header

        current_message += entry

    if current_message.strip() != header.strip():
        chunks.append(current_message)

    for index, message in enumerate(chunks):
        send_telegram(message)
        print(
            f"Notifica Telegram inviata "
            f"({index + 1}/{len(chunks)})."
        )


def main():
    print("Avvio monitor CarteMagic.")

    current_products = {}

    for url, category in SOURCES:
        try:
            found = scan(url, category)
            current_products.update(found)

        except requests.HTTPError as error:
            print(
                f"Errore HTTP durante il controllo di "
                f"{category}: {error}"
            )

        except requests.RequestException as error:
            print(
                f"Errore di rete durante il controllo di "
                f"{category}: {error}"
            )

    current_urls = set(current_products.keys())

    if not current_urls:
        raise RuntimeError(
            "Nessun prodotto riconosciuto. "
            "Non aggiorno lo storico per evitare errori."
        )

    print(
        f"Totale prodotti TCG riconosciuti: "
        f"{len(current_urls)}"
    )

    previous_urls = load_state()

    # Primo avvio: crea lo storico senza notificare
    # i prodotti già presenti sul sito.
    if not os.path.exists(BASELINE_FILE):
        save_state(current_urls)

        with open(
            BASELINE_FILE,
            "w",
            encoding="utf-8",
        ) as file:
            file.write(
                "Storico iniziale creato correttamente.\n"
            )

        print(
            f"Storico inizializzato con "
            f"{len(current_urls)} prodotti. "
            "Nessuna notifica inviata."
        )
        return

    # Se lo storico manca dopo il primo avvio,
    # non inviare notifiche potenzialmente massive.
    if previous_urls is None:
        raise RuntimeError(
            "Lo storico dei prodotti manca o non è valido. "
            "Non invio notifiche per sicurezza."
        )

    new_urls = current_urls - previous_urls

    # Conserva anche gli URL visti in precedenza,
    # evitando di ripetere notifiche per prodotti spariti
    # e poi ricomparsi.
    updated_urls = previous_urls | current_urls
    save_state(updated_urls)

    if not new_urls:
        print("Nessun nuovo prodotto TCG.")
        return

    new_products = [
        current_products[url]
        for url in sorted(new_urls)
    ]

    print(
        f"Nuovi prodotti trovati: {len(new_products)}"
    )

    send_new_products(new_products)


if __name__ == "__main__":
    main()
