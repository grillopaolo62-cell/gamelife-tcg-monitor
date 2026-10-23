
import os
import json
import urllib.request
import urllib.error
from html.parser import HTMLParser

URL = "https://www.gamelife.it/224-carte-collezionabili"
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
STATE_FILE = "seen_products.json"


class ProductParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        href = attrs.get("href", "")
        classes = attrs.get("class", "").lower()
        marker = (href + " " + classes).lower()

        if tag == "a" and href and (
            "product" in marker or "prodotto" in marker
        ):
            self.current = {"url": href, "text": ""}

    def handle_data(self, data):
        if self.current:
            self.current["text"] += " " + data.strip()

    def handle_endtag(self, tag):
        if tag == "a" and self.current:
            name = " ".join(self.current["text"].split())
            url = self.current["url"]

            if name and len(name) > 3:
                self.links.append({"url": url, "text": name})

            self.current = None


def telegram(message):
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
        raise RuntimeError("Telegram non ha accettato il messaggio")


def fetch_page():
    request = urllib.request.Request(
        URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "it-IT,it;q=0.9,en;q=0.8"
        }
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"Gamelife ha rifiutato la richiesta: HTTP {error.code}. "
            "Potrebbe essere necessario un metodo di accesso diverso."
        ) from error


def main():
    html = fetch_page()

    parser = ProductParser()
    parser.feed(html)

    products = {}

    for product in parser.links:
        url = product["url"]

        if url.startswith("/"):
            url = "https://www.gamelife.it" + url
        elif not url.startswith("https://www.gamelife.it/"):
            continue

        products[url] = product["text"]

    if not products:
        raise RuntimeError(
            "Nessun prodotto riconosciuto nella pagina. "
            "La struttura HTML potrebbe essere diversa da quella prevista."
        )

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            seen = json.load(file)
    except FileNotFoundError:
        seen = None

    current = set(products.keys())

    if seen is None:
        with open(STATE_FILE, "w", encoding="utf-8") as file:
            json.dump(sorted(current), file, ensure_ascii=False)

        telegram(
            "✅ Monitor Gamelife avviato!\n"
            f"Prodotti rilevati nella prima scansione: {len(current)}.\n"
            "Ti avviserò quando verranno individuati nuovi prodotti."
        )
        return

    new_products = current - set(seen)

    for url in sorted(new_products):
        telegram(
            "🆕 Nuovo prodotto su Gamelife:\n"
            f"{products[url]}\n{url}"
        )

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(sorted(current), file, ensure_ascii=False)


if __name__ == "__main__":
    main()
