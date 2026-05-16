from bs4 import BeautifulSoup


def extract_html(raw_bytes: bytes) -> str:
    soup = BeautifulSoup(raw_bytes, "lxml")

    for tag in soup(["script", "style", "nav", "footer", "head"]):
        tag.decompose()

    return soup.get_text(separator="\n", strip=True)
