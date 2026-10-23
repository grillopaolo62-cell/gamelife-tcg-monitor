
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
    (f"{BASE_URL}/carte-collezionabili/", "Catalogo TCG"),
    (f"{BASE_URL}/categoria/preordini/", "Preordini TCG"),
]

KEYWORDS = [
    "pokemon", "one piece", "magic", "yu-gi-oh", "yugioh",
    "lorcana", "dragon ball", "digimon", "riftbound",
    "union arena", "star wars unlimited", "final fantasy",
    "flesh and blood", "battle spirits", "gundam", "palworld",
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

MAX_PAGES = 10
REQUEST_TIMEOUT = 20


def load_state():
    if not os.path.exists(STATE_FILE):
        return None

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, dict) and isinstance(data.get("products"), list):
            return {
                url for url in data["products"]
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


def scan(url, category):
    products = {}
    session = requests.Session()
    session.headers.update(HEADERS)

    for page_number in range(1, MAX_PAGES + 1):
        if page_number == 1:
            page_url = url
        else:
            page_url = f"{url}?product-page={page_number}"

        try:
            response = session.get(
                page_url,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as error:
            print(f"ERRORE DI RETE: {page_url} - {error}")
            break

        print(f"\nSEZIONE: {category}")
        print(f"URL: {page_url}")
        print(f"STATUS HTTP: {response.status_code}")
        print(f"LUNGHEZZA PAGINA: {len(response.text)}")
        print(f"INIZIO RISPOSTA: {response.text[:300]!r}")

        if response.status_code == 403:
            print("ACCESSO BLOCCATO: salto questa sezione.")
            break

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Cerca tutti i link ai prodotti, senza dipendere
        # da una specifica struttura grafica della pagina.
        links = soup.select('a[href*="/prodotto/"]')

        print(f"LINK PRODOTTO TROVATI: {len(links)}")

        if not links:
            break

        found_on_page = 0

        for link in links:
            product_url = urljoin(page_url, link.get("href", ""))
            product_url = product_url.split("#")[0].rstrip("/") + "/"

            title = link.get_text(" ", strip=True)

            if not title:
                parent = link.find_parent(
                    ["li", "article", "div"]
                )
                if parent:
                    title_element = parent.select_one(
                        ".woocommerce-loop-product__title, h2, h3"
                    )
                    if title_element:
                        title = title_element.get_text(
                            " ", strip=True
                        )

            if not title:
                title = product_url.rstrip("/").split("/")[-1]
                title = title.replace("-", " ")

            if not matches_keywords(title, product_url):
                continue

            parent = link.find_parent(
                ["li", "article", "div"]
            )
            price = ""

            if parent:
                price_element = parent.select_one(
                    ".price, .woocommerce-Price-amount"
                )
                if price_element:
                    price = price_element.get_text(
                        " ", strip=True
                    )

            products[product_url] = {
                "url": product_url,
                "title": title,
                "price": price,
                "category": category,
            }
            found_on_page += 1

        print(f"PRODOTTI TCG TROVATI: {found_on_page}")

        # Se la pagina non contiene nuovi link, non continuare
        # a richiedere pagine inutilmente.
        if page_number > 1 and found_on_page == 0:
            break

        time.sleep(1)

    session.close()
    return products


def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError(
            "Mancano i Secrets Telegram in GitHub."
        )

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    response.raise_for_status()

    if not response.json().get("ok"):
        raise RuntimeError("Telegram non ha accettato il messaggio.")


def send_new_products(products):
    header = "🆕 NOVITÀ TCG SU CARTEMAGIC\n\n"
    messages = []
    current = header

    for product in products:
        entry = f"📦 {product['title']}\n"
        entry += f"📂 {product['category']}\n"

        if product.get("price"):
            entry += f"🏷️ {product['price']}\n"

        entry += f"{product['url']}\n\n"

        if len(current) + len(entry) > 3500:
            messages.append(current)
            current = header

        current += entry

    if current != header:
        messages.append(current)

    for message in messages:
        send_telegram(message)
        print("Notifica Telegram inviata.")


def main():
    print("Avvio monitor CarteMagic.")
    current_products = {}

    for url, category in SOURCES:
        try:
            current_products.update(scan(url, category))
        except requests.RequestException as error:
            print(f"ERRORE HTTP/RETE in {category}: {error}")

    current_urls = set(current_products)

    print(f"\nTOTALE PRODOTTI RICONOSCIUTI: {len(current_urls)}")

    # Se non troviamo prodotti, non modifichiamo lo storico
    # e non inviamo notifiche.
    if not current_urls:
        raise RuntimeError(
            "Nessun prodotto riconosciuto. "
            "Lo storico non è stato modificato."
        )

    previous_urls = load_state()

    # Inizializzazione silenziosa, solo se il marcatore non esiste.
    if not os.path.exists(BASELINE_FILE):
        save_state(current_urls)

        with open(BASELINE_FILE, "w", encoding="utf-8") as file:
            file.write("Storico iniziale creato.\n")

        print(
            f"Storico inizializzato con {len(current_urls)} prodotti. "
            "Nessuna notifica inviata."
        )
        return

    if previous_urls is None:
        raise RuntimeError(
            "Storico assente o non valido: "
            "interrompo per evitare notifiche massive."
        )

    new_urls = current_urls - previous_urls
    save_state(previous_urls | current_urls)

    if not new_urls:
        print("Nessun nuovo prodotto TCG.")
        return

    new_products = [
        current_products[url] for url in sorted(new_urls)
    ]

    print(f"NUOVI PRODOTTI: {len(new_products)}")
    send_new_products(new_products)


if __name__ == "__main__":
    main()
