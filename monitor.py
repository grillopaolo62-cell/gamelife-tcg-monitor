
import os
import json
import urllib.request
import urllib.error
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

URL = "https://www.cartemagic.com/carte-collezionabili/"
SITE = "cartemagic.com"
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
STATE_FILE = "seen_products.json"


class ProductParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.products = []
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "a":
            href = attrs.get("href", "")
            classes = attrs.get("class", "").lower()
            full_url = urljoin(URL, href)
            path = urlparse(full_url).path.lower()

            if (
                urlparse(full_url).netloc.endswith(SITE)
                and (
                    "/prodotto/" in path
                    or "woocommerce-loop-product__link" in classes
                )
            ):
                self.anchor = {
                    "url": full_url.split("?")[0].rstrip("/") + "/",
                    "text": ""
                }

        elif tag == "img" and self.anchor:
            alt = attrs.get("alt", "").strip()
            if alt:
                self.anchor["text"] += " " + alt

    def handle_data(self, data):
        if self.anchor:
            self.anchor["text"] += " " + data.strip()

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor:
            name = " ".join(self.anchor["text"].split())
            if name:
                self.products.append({
                    "url": self.anchor["url"],
                    "name": name
                })
            self.anchor = None


def send_telegram(message):
    data = json.dumps({
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": True
    }).encode("utf-8")

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data=data,
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.loads(response.read().decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError("Invio Telegram non riuscito")


def fetch_page():
    request = urllib.request.Request(
        URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "it-IT,it;q=0.9,en;q=0.8"
        }
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"CarteMagic ha restituito HTTP {error.code}. "
            "Bisogna verificare un metodo alternativo di lettura."
        ) from error


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_state(products):
    state = {
        "site": SITE,
        "products": sorted(products)
    }

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)


def main():
    html = fetch_page()

    parser = ProductParser()
    parser.feed(html)

    products = {}
    for product in parser.products:
        products[product["url"]] = product["name"]

    if not products:
        raise RuntimeError(
            "Non ho trovato prodotti nella pagina. "
            "La struttura HTML potrebbe essere diversa da quella prevista."
        )

    state = load_state()

    # Al primo controllo, oppure al cambio di sito,
    # registra i prodotti presenti senza inviare notifiche in massa.
    if not isinstance(state, dict) or state.get("site") != SITE:
        save_state(products.keys())
        send_telegram(
            "✅ Monitor CarteMagic avviato!\n"
            f"Prodotti riconosciuti: {len(products)}.\n"
            "Questa è la scansione iniziale: "
            "ti avviserò dei nuovi prodotti rilevati in seguito."
        )
        return

    previous = set(state.get("products", []))
    current = set(products.keys())
    new_products = current - previous

    for product_url in sorted(new_products):
        send_telegram(
            "🆕 Nuovo prodotto su CarteMagic:\n"
            f"{products[product_url]}\n"
            f"{product_url}"
        )

    save_state(current)

    print(
        f"Controllo completato: {len(products)} prodotti, "
        f"{len(new_products)} nuovi."
    )


if __name__ == "__main__":
    main()
