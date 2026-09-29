"""One-time import of real URLs from an old watchlist."""
import sys
from pathlib import Path
from urllib.parse import urlparse

from .db import make_engine, session_factory
from .service import add_product


def main(path="watchlist.txt"):
    factory = session_factory(make_engine())
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        url = raw.strip()
        if not url or url.startswith("#"):
            continue
        slug = urlparse(url).path.rstrip("/").split("/")[-1]
        name = slug.replace("-", " ").replace("_", " ").title()[:200] or "Imported product"
        with factory() as db:
            try:
                add_product(db, name, url)
                print("Imported:", name)
            except ValueError as exc:
                print("Skipped:", exc)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "watchlist.txt")
