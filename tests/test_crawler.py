"""离线测试：用简化的 HTML 样例模拟豆瓣页面，不发送任何网络请求。"""
import json

import pandas as pd
import pytest

from douban_crawler.client import BlockedError
from douban_crawler.crawler import MOVIE_URL, REVIEWS_URL, USER_REVIEWS_URL, Crawler
from douban_crawler.parsers import (
    has_next_page,
    parse_movie,
    parse_review_authors,
    parse_user_reviews,
)
from douban_crawler.pipeline import clean, process

REVIEWS_PAGE = """
<div class="review-list  ">
  <div><header class="main-hd">
    <a href="https://www.douban.com/people/alice/"><img></a>
    <a href="https://www.douban.com/people/alice/">Alice</a></header></div>
  <div><header class="main-hd">
    <a href="https://www.douban.com/people/bob/"><img></a>
    <a href="https://www.douban.com/people/bob/">Bob</a></header></div>
</div>"""


def user_page(entries, next_page=False):
    items = "".join(
        f'<div class="clst report-link"><span class="pl ll obss">'
        f'<span title="{title}"></span>'
        f'<a href="https://movie.douban.com/review/1/">review</a>'
        f'<a href="https://movie.douban.com/subject/{sid}/">movie</a></span></div>'
        for sid, title in entries
    )
    nxt = '<span class="next"><a href="?start=10">后页</a></span>' if next_page else ""
    return f"<div>{items}{nxt}</div>"


def movie_page(title, genres):
    g = "".join(f'<span property="v:genre">{x}</span>' for x in genres)
    return (
        f'<div id="content"><h1><span property="v:itemreviewed">{title}</span>'
        f'<span class="year">(2019)</span></h1><div id="info">{g}</div></div>'
    )


# ---------------- 解析 ----------------

def test_parse_review_authors_dedupes():
    assert parse_review_authors(REVIEWS_PAGE) == ["alice", "bob"]


def test_parse_user_reviews_maps_ratings_and_skips_unrated():
    html = user_page([("101", "力荐"), ("102", "很差"), ("103", "")])
    assert parse_user_reviews(html) == [
        {"subject_id": "101", "rating": 5},
        {"subject_id": "102", "rating": 1},
    ]


def test_has_next_page():
    assert has_next_page(user_page([], next_page=True))
    assert not has_next_page(user_page([]))


def test_parse_movie():
    assert parse_movie(movie_page(" 调音师 Andhadhun ", ["喜剧", "悬疑"])) == {
        "title": "调音师 Andhadhun",
        "genres": ["喜剧", "悬疑"],
    }
    assert parse_movie("<html></html>") is None


def test_parsers_handle_empty_input():
    assert parse_review_authors("") == []
    assert parse_user_reviews("") == []
    assert parse_movie("") is None


# ---------------- 爬取流程 ----------------

class FakeClient:
    def __init__(self, pages, block_on=None):
        self.pages, self.block_on, self.calls = pages, block_on, []

    def get(self, url):
        self.calls.append(url)
        if url == self.block_on:
            raise BlockedError(url)
        return self.pages.get(url, "")


@pytest.fixture
def site():
    return {
        REVIEWS_URL.format(sid="1", start=0): REVIEWS_PAGE,
        USER_REVIEWS_URL.format(uid="alice", start=0): user_page([("101", "推荐")], next_page=True),
        USER_REVIEWS_URL.format(uid="alice", start=10): user_page([("102", "还行")]),
        USER_REVIEWS_URL.format(uid="bob", start=0): user_page([("101", "较差")]),
        MOVIE_URL.format(sid="101"): movie_page("电影甲", ["剧情"]),
        MOVIE_URL.format(sid="102"): movie_page("电影乙", ["喜剧"]),
    }


def test_full_crawl_paginates_and_caches_movies(tmp_path, site):
    client = FakeClient(site)
    assert Crawler(client, tmp_path).run("1", review_pages=2, max_users=10, user_pages=5)

    ratings = pd.read_csv(tmp_path / "ratings_raw.csv", dtype=str)
    assert len(ratings) == 3
    # 电影 101 被两个用户评过，但详情页只请求一次
    assert client.calls.count(MOVIE_URL.format(sid="101")) == 1
    assert (tmp_path / "users_done.txt").read_text().split() == ["alice", "bob"]


def test_resume_after_block(tmp_path, site):
    blocked = USER_REVIEWS_URL.format(uid="bob", start=0)
    assert not Crawler(FakeClient(site, block_on=blocked), tmp_path).run("1", 2, 10, 5)
    assert (tmp_path / "users_done.txt").read_text().split() == ["alice"]

    client = FakeClient(site)
    assert Crawler(client, tmp_path).run("1", 2, 10, 5)
    # 续爬时不再请求 alice 的页面和已缓存的电影
    assert not any("alice" in c for c in client.calls)
    assert MOVIE_URL.format(sid="101") not in client.calls
    assert len(pd.read_csv(tmp_path / "ratings_raw.csv")) == 3


# ---------------- 清洗 ----------------

def test_clean_dedupes_filters_and_anonymizes():
    ratings = pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u1", "u2", "u2", "u3"],
            "subject_id": ["a", "a", "b", "a", "c", "b"],
            "rating": [3, 5, 4, 2, 1, 4],
        }
    )
    movies = pd.DataFrame(
        {
            "subject_id": ["a", "b", "c"],
            "title": ["A", "B", "C"],
            "genres": [["剧情"], ["喜剧"], ["真人秀"]],
        }
    )
    r, m = clean(ratings, movies, exclude_genres=["真人秀"])

    assert "真人秀" not in ",".join(m["genres"])
    assert len(r) == 4  # 去掉 1 条重复 + 1 条被剔除类型的评分
    assert set(r["user_id"]) == {1, 2, 3}  # 原始用户名不再出现
    u1_a = r[(r["user_id"] == 1) & (r["movie_id"] == 1)]
    assert u1_a["rating"].item() == 5  # 重复评分保留最后一条


def test_clean_iterative_threshold():
    ratings = pd.DataFrame(
        {"user_id": ["u1", "u1", "u2", "u2", "u3"],
         "subject_id": ["a", "b", "a", "b", "c"],
         "rating": [5, 4, 3, 2, 1]}
    )
    movies = pd.DataFrame({"subject_id": list("abc"), "title": list("ABC"),
                           "genres": [["剧情"]] * 3})
    r, m = clean(ratings, movies, min_user_ratings=2, min_movie_ratings=2)
    assert len(r) == 4 and len(m) == 2


def test_process_writes_files(tmp_path, site):
    raw = tmp_path / "raw"
    Crawler(FakeClient(site), raw).run("1", 2, 10, 5)
    summary = process(raw, tmp_path / "out")
    assert "用户数 2" in summary
    movies = pd.read_csv(tmp_path / "out" / "movies.csv")
    assert list(movies.columns) == ["movie_id", "subject_id", "title", "genres"]
