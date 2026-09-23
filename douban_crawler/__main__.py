"""Command-line entry point: python -m douban_crawler {crawl,process} ..."""
from __future__ import annotations

import argparse
import logging
import os
import sys

from .client import PoliteClient
from .crawler import Crawler
from .pipeline import process


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="douban_crawler",
        description="Douban movie rating crawler",
    )
    p.add_argument("-v", "--verbose", action="store_true")

    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("crawl", help="Collect raw data")
    c.add_argument(
        "--subject",
        required=True,
        help="Douban movie ID; users are collected from its review section",
    )
    c.add_argument(
        "--review-pages",
        type=int,
        default=5,
        help="Number of review pages to scan for collecting users (20 reviews per page)",
    )
    c.add_argument("--max-users", type=int, default=50)
    c.add_argument(
        "--user-pages",
        type=int,
        default=3,
        help="Maximum number of review pages to scan for each user (10 reviews per page)",
    )
    c.add_argument("--min-delay", type=float, default=2.0)
    c.add_argument("--max-delay", type=float, default=5.0)
    c.add_argument("--out", default="data/raw")

    pr = sub.add_parser("process", help="Clean, deduplicate, and anonymize data")
    pr.add_argument("--raw", default="data/raw")
    pr.add_argument("--out", default="data/processed")
    pr.add_argument(
        "--exclude-genres",
        nargs="*",
        default=[],
        help="Exclude movies containing any of these genres",
    )
    pr.add_argument(
        "--min-user-ratings",
        type=int,
        default=1,
        help="Minimum number of ratings required for a user",
    )
    pr.add_argument(
        "--min-movie-ratings",
        type=int,
        default=1,
        help="Minimum number of ratings required for a movie",
    )

    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.cmd == "crawl":
        client = PoliteClient(
            args.min_delay,
            args.max_delay,
            cookie=os.getenv("DOUBAN_COOKIE"),
        )
        ok = Crawler(client, args.out).run(
            args.subject,
            args.review_pages,
            args.max_users,
            args.user_pages,
        )
        return 0 if ok else 2

    print(
        process(
            args.raw,
            args.out,
            exclude_genres=args.exclude_genres,
            min_user_ratings=args.min_user_ratings,
            min_movie_ratings=args.min_movie_ratings,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())