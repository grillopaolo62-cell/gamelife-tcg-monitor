
import os
import json
import hashlib
import urllib.request
import urllib.error
from html.parser import HTMLParser

URL = "https://www.gamelife.it/collezionabili"
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
STATE_FILE = "seen_products.json"


class ProductParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.in_product = False
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").lower()
        href = attrs.get("href", "")

        if tag == "a" and href and any(
            word in (classes + " " + href).lower()
            for word in ["product", "prodotto"]
        ):
            self.current = {"url": href, "text": ""}
            self.in_product = True

    def handle_data(self, data):
        if self.in_product and self.current:
            self.current["text"] += " " + data.strip()

    def handle_endtag(self, tag):
        if tag == "a" and self.in_product and self.current:
            text = " ".join(self.current["text"].split())
            if text and len(text) > 3:
                self.links.append(self.current | {"text": text})
            self.current = None
            self.in_product = False


def telegram(message):
    data = json.dumps({
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": True
    }).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.loads(response.read())
        if not result.get("ok"):
            raise RuntimeError("Telegram non ha accettato il messaggio")


def fetch_page():
    request = urllib.request.Request(
        URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; TCGMonitor/1.0)"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def main():
    html = fetch_page()
    parser = ProductParser()
    parser.feed(html)

    products = {}
    for product in parser.links:
        url = product["url"]
        if url.startswith("/"):
            url = "https://www.gamelife.it" + url
        elif not url.startswith("http"):
            continue
        products[url] = product["text"]

    if not products:
        raise RuntimeError(
            "Nessun prodotto riconosciuto: il catalogo potrebbe richiedere "
            "JavaScript o una struttura HTML diversa. Non aggiorno lo stato."
        )

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            seen = json.load(file)
    except FileNotFoundError:
        seen = None

    current = set(products)
    if seen is None:
        # Prima esecuzione: registra i prodotti esistenti senza inviare
        # centinaia di notifiche iniziali.
        with open(STATE_FILE, "w", encoding="utf-8") as file:
            json.dump(sorted(current), file)
        telegram(
            "✅ Monitor Gamelife attivato!\n"
            f"Ho rilevato {len(current)} prodotti nella prima scansione. "
            "Ti avviserò quando individuerò nuovi prodotti."
        )
        return

    new_products = current - set(seen)
    for product_url in sorted(new_products):
        telegram(f"🆕 Nuovo prodotto su Gamelife:\n{products[product_url]}\n{product_url}")

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(sorted(current), file)


if __name__ == "__main__":
    main()
