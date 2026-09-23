"""Data cleaning and preprocessing.

Replaces the original manual Excel/VBA workflow for removing missing values,
deduplicating records, filtering sparse users/movies, and anonymizing IDs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def load_raw(raw_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load raw ratings and movie metadata from disk."""
    raw = Path(raw_dir)

    ratings = pd.read_csv(
        raw / "ratings_raw.csv",
        dtype={"user_id": str, "subject_id": str},
    )

    with (raw / "movies_raw.jsonl").open(encoding="utf-8") as f:
        movies = pd.DataFrame(
            [json.loads(line) for line in f if line.strip()]
        )

    movies["subject_id"] = movies["subject_id"].astype(str)

    return ratings, movies


def clean(
    ratings: pd.DataFrame,
    movies: pd.DataFrame,
    exclude_genres: list[str] | None = None,
    min_user_ratings: int = 1,
    min_movie_ratings: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Clean, filter, deduplicate, and anonymize the dataset.

    Returns:
        A tuple ``(ratings, movies)`` containing processed ratings and
        movie metadata. User and movie IDs are replaced with consecutive
        integer IDs starting from 1.
    """
    # Remove records with missing required fields.
    ratings = ratings.dropna(
        subset=["user_id", "subject_id", "rating"]
    )

    # Keep only valid ratings on the 1-5 scale.
    ratings = ratings[ratings["rating"].between(1, 5)]

    # Keep only the last rating when a user has multiple records
    # for the same movie.
    ratings = ratings.drop_duplicates(
        subset=["user_id", "subject_id"],
        keep="last",
    )

    # Remove duplicate movie metadata.
    movies = movies.drop_duplicates(
        subset="subject_id",
        keep="last",
    )

    # Optionally exclude selected movie genres.
    if exclude_genres:
        banned = set(exclude_genres)
        movies = movies[
            ~movies["genres"].apply(
                lambda genres: bool(banned & set(genres))
            )
        ]

    # Keep only ratings for movies that remain after genre filtering.
    ratings = ratings[
        ratings["subject_id"].isin(movies["subject_id"])
    ]

    # Iterative filtering:
    # removing low-frequency users can make some movies fall below
    # the minimum rating threshold, and vice versa. Repeat until stable.
    while len(ratings):
        user_counts = ratings["user_id"].map(
            ratings["user_id"].value_counts()
        )
        movie_counts = ratings["subject_id"].map(
            ratings["subject_id"].value_counts()
        )

        keep = (
            (user_counts >= min_user_ratings)
            & (movie_counts >= min_movie_ratings)
        )

        if keep.all():
            break

        ratings = ratings[keep]

    # Keep only movies that still have at least one rating.
    movies = movies[
        movies["subject_id"].isin(ratings["subject_id"])
    ].reset_index(drop=True)

    # Replace movie IDs with consecutive integer IDs.
    movies.insert(
        0,
        "movie_id",
        range(1, len(movies) + 1),
    )

    movie_map = dict(
        zip(movies["subject_id"], movies["movie_id"])
    )

    # Replace raw Douban user IDs with anonymous integer IDs.
    # Original user IDs are not included in the processed output.
    user_map = {
        uid: i
        for i, uid in enumerate(
            ratings["user_id"].unique(),
            1,
        )
    }

    out = pd.DataFrame(
        {
            "user_id": ratings["user_id"]
            .map(user_map)
            .to_numpy(),
            "movie_id": ratings["subject_id"]
            .map(movie_map)
            .to_numpy(),
            "rating": ratings["rating"]
            .astype(int)
            .to_numpy(),
        }
    )

    # Store genres as comma-separated strings in the CSV output.
    movies_out = movies.assign(
        genres=movies["genres"].str.join(",")
    )

    return out, movies_out[
        ["movie_id", "subject_id", "title", "genres"]
    ]


def summarize(ratings: pd.DataFrame) -> str:
    """Generate a summary of the processed rating matrix."""
    n_users = ratings["user_id"].nunique()
    n_movies = ratings["movie_id"].nunique()
    n_ratings = len(ratings)

    density = (
        n_ratings / (n_users * n_movies)
        if n_users and n_movies
        else 0.0
    )

    distribution = {
        int(k): int(v)
        for k, v in (
            ratings["rating"]
            .value_counts()
            .sort_index()
            .items()
        )
    }

    return (
        f"Users: {n_users}, Movies: {n_movies}, "
        f"Ratings: {n_ratings}\n"
        f"Matrix density: {density:.2%} "
        f"(sparsity: {1 - density:.2%})\n"
        f"Rating distribution: {distribution}"
    )


def process(raw_dir, out_dir, **kwargs) -> str:
    """Run the complete data-processing pipeline."""
    ratings, movies = clean(
        *load_raw(raw_dir),
        **kwargs,
    )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    ratings.to_csv(
        out / "ratings.csv",
        index=False,
    )

    movies.to_csv(
        out / "movies.csv",
        index=False,
    )

    return summarize(ratings)