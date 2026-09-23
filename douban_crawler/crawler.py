"""Crawling pipeline: movie reviews -> review authors -> user ratings -> movie details.

All results are incrementally written to disk. If the process is interrupted
(including being blocked), rerunning the crawler will resume from the last checkpoint.
"""
from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

from .client import BlockedError, PoliteClient
from .parsers import has_next_page, parse_movie, parse_review_authors, parse_user_reviews

log = logging.getLogger(__name__)

REVIEWS_URL = "https://movie.douban.com/subject/{sid}/reviews?sort=time&start={start}"
USER_REVIEWS_URL = "https://movie.douban.com/people/{uid}/reviews?start={start}"
MOVIE_URL = "https://movie.douban.com/subject/{sid}/"

REVIEWS_PER_PAGE = 20
USER_REVIEWS_PER_PAGE = 10


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class Crawler:
    def __init__(self, client: PoliteClient, out_dir: str | Path) -> None:
        self.client = client
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.ratings_path = self.out / "ratings_raw.csv"
        self.movies_path = self.out / "movies_raw.jsonl"
        self.done_path = self.out / "users_done.txt"

        # Resume from checkpoint: completed users and already fetched movies
        # will not be requested again.
        self.done_users = set(_read_lines(self.done_path))
        self.known_movies = {
            json.loads(line)["subject_id"]
            for line in _read_lines(self.movies_path)
        }

    # ---------- Step 1: Collect users from the seed movie's review section ----------
    def collect_users(self, seed_subject: str, pages: int) -> list[str]:
        users: list[str] = []

        for page in range(pages):
            url = REVIEWS_URL.format(
                sid=seed_subject,
                start=page * REVIEWS_PER_PAGE,
            )
            found = parse_review_authors(self.client.get(url))

            if not found:
                break

            users.extend(u for u in found if u not in users)
            log.info(
                "Review page %d: %d users collected",
                page + 1,
                len(users),
            )

        return users

    # ---------- Step 2: Crawl a user's movie ratings with automatic pagination ----------
    def crawl_user(self, uid: str, max_pages: int) -> list[dict]:
        rows: list[dict] = []

        for page in range(max_pages):
            url = USER_REVIEWS_URL.format(
                uid=uid,
                start=page * USER_REVIEWS_PER_PAGE,
            )
            html = self.client.get(url)

            rows.extend(
                {"user_id": uid, **r}
                for r in parse_user_reviews(html)
            )

            if not has_next_page(html):
                break

        return rows

    # ---------- Step 3: Fetch movie information with caching ----------
    def fetch_movie(self, sid: str) -> None:
        if sid in self.known_movies:
            return

        info = parse_movie(self.client.get(MOVIE_URL.format(sid=sid)))

        if info is None:
            log.warning("Failed to parse movie %s; skipping", sid)
            return

        with self.movies_path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {"subject_id": sid, **info},
                    ensure_ascii=False,
                )
                + "\n"
            )

        self.known_movies.add(sid)

    def _append_ratings(self, rows: list[dict]) -> None:
        new_file = not self.ratings_path.exists()

        with self.ratings_path.open(
            "a",
            encoding="utf-8",
            newline="",
        ) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["user_id", "subject_id", "rating"],
            )

            if new_file:
                writer.writeheader()

            writer.writerows(rows)

    def _mark_done(self, uid: str) -> None:
        with self.done_path.open("a", encoding="utf-8") as f:
            f.write(uid + "\n")

        self.done_users.add(uid)

    def run(
        self,
        seed_subject: str,
        review_pages: int,
        max_users: int,
        user_pages: int,
    ) -> bool:
        """Run the complete crawling pipeline.

        Returns True on successful completion and False if the request is blocked.
        Progress is saved before returning on a block.
        """
        try:
            users = self.collect_users(
                seed_subject,
                review_pages,
            )[:max_users]

            todo = [u for u in users if u not in self.done_users]

            log.info(
                "%d users collected, %d remaining to process",
                len(users),
                len(todo),
            )

            for i, uid in enumerate(todo, 1):
                rows = self.crawl_user(uid, user_pages)

                for r in rows:
                    self.fetch_movie(r["subject_id"])

                # Write and mark the user as complete only after all of the
                # user's data has been successfully crawled.
                self._append_ratings(rows)
                self._mark_done(uid)

                log.info(
                    "[%d/%d] User %s: %d ratings",
                    i,
                    len(todo),
                    uid,
                    len(rows),
                )

        except BlockedError as e:
            log.error(
                "%s\nCompleted progress has been saved. "
                "Rerun the crawler after resolving the issue to resume from the checkpoint.",
                e,
            )
            return False

        return True