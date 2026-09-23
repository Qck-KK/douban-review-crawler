"""Page parsers.

All functions are pure functions that take HTML strings as input,
making them easy to test offline.
"""

from __future__ import annotations

import re

from lxml import etree

SUBJECT_RE = re.compile(r"movie\.douban\.com/subject/(\d+)")

PEOPLE_RE = re.compile(r"douban\.com/people/([^/?#]+)")

# Map Douban star-rating labels to numerical ratings from 1 to 5.
RATING_MAP = {
    "力荐": 5,
    "推荐": 4,
    "还行": 3,
    "较差": 2,
    "很差": 1,
}


def _tree(html: str):
    return etree.HTML(html) if html and html.strip() else None


def parse_review_authors(html: str) -> list[str]:
    """Extract review authors' Douban user IDs from a movie review page.

    Duplicate user IDs are removed while preserving their original order.
    """
    tree = _tree(html)

    if tree is None:
        return []

    hrefs = tree.xpath(
        '//*[contains(@class, "review-list")]'
        '//*[contains(@class, "main-hd")]//a/@href'
    )

    ids: list[str] = []

    for href in hrefs:
        m = PEOPLE_RE.search(href)
        if m and m.group(1) not in ids:
            ids.append(m.group(1))

    return ids


def parse_user_reviews(html: str) -> list[dict]:
    """Extract movie IDs and ratings from a user's review page.

    Reviews without a rating are skipped.
    """
    tree = _tree(html)

    if tree is None:
        return []

    results: list[dict] = []

    for item in tree.xpath('//*[contains(@class, "report-link")]'):
        rating = next(
            (
                RATING_MAP[t]
                for t in item.xpath(".//@title")
                if t in RATING_MAP
            ),
            None,
        )

        subject_id = next(
            (
                m.group(1)
                for h in item.xpath(".//@href")
                if (m := SUBJECT_RE.search(h))
            ),
            None,
        )

        if rating is not None and subject_id is not None:
            results.append(
                {
                    "subject_id": subject_id,
                    "rating": rating,
                }
            )

    return results


def has_next_page(html: str) -> bool:
    """Return whether the page contains a link to the next page."""
    tree = _tree(html)

    return bool(
        tree is not None
        and tree.xpath('//span[@class="next"]/a')
    )


def parse_movie(html: str) -> dict | None:
    """Extract the movie title and genres from a movie detail page."""
    tree = _tree(html)

    if tree is None:
        return None

    title = tree.xpath(
        '//*[@id="content"]/h1/span[@property="v:itemreviewed"]/text()'
    )

    if not title:
        title = tree.xpath(
            '//*[@id="content"]/h1/span[1]/text()'
        )

    if not title:
        return None

    genres = tree.xpath(
        '//*[@id="info"]//span[@property="v:genre"]/text()'
    )

    return {
        "title": title[0].strip(),
        "genres": [g.strip() for g in genres],
    }