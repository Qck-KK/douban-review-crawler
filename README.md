# douban-review-crawler

A Python crawler for collecting user ratings and movie information from Douban, then cleaning and transforming the data into a format directly usable for recommendation systems such as collaborative filtering.

This project originated from the data collection part of my undergraduate thesis, *The Construction of a Movie Recommendation System in R*. The original crawler required manually changing user IDs and running the crawler one user at a time, while data cleaning was performed manually using Excel and VBA. This project rewrites the entire workflow as a reproducible, checkpointable command-line tool.

## Features

* **Complete data collection pipeline**: collect users from a seed movie's review section → crawl each user's movie reviews and ratings with automatic pagination → fetch the corresponding movie titles and genres

* **Request control and block detection**: randomized delays between requests, automatic exponential backoff for 429/5xx responses, and safe termination when browser verification or access blocks are detected

* **Checkpoint/resume**: data is written incrementally to disk by user; when the crawler is restarted, completed users are skipped

* **Movie caching**: each movie detail page is requested at most once

* **Data cleaning**: remove missing values, keep only the latest rating when the same user has multiple ratings for the same movie, optionally exclude movies by genre, and iteratively filter users and movies by minimum rating counts

* **Anonymization**: replace original Douban user IDs with consecutive anonymous IDs in the processed output

* **Offline tests**: parsing, crawling workflow, checkpoint/resume, and data-cleaning logic can be tested without network access

## Usage

```bash
pip install -r requirements.txt

# Set DOUBAN_COOKIE as described below before crawling.

# 1. Crawl:
#    collect up to 50 users from the first 5 review pages
#    of movie 3742360.
#
#    --subject is the numeric ID in:
#    movie.douban.com/subject/<ID>/

python -m douban_crawler crawl --subject 3742360 --review-pages 5 --max-users 50

# 2. Process:
#    exclude selected genres and keep users and movies
#    with at least 3 ratings.

python -m douban_crawler process --exclude-genres 真人秀 --min-user-ratings 3 --min-movie-ratings 3
```

### Set Cookie (Required)

Douban currently applies browser verification to automated requests, including redirects to `sec.douban.com`. In the current environment, unauthenticated requests may not pass this verification, so **you should log in to Douban and provide a Cookie before crawling**.

1. Log in to Douban in a browser and open `movie.douban.com`.

2. Press `F12` to open Developer Tools → **Network**, refresh the page, and select the first `movie.douban.com` request with type `document`.

3. In **Request Headers**, copy the complete `Cookie` header.

4. Set the environment variable in your terminal:

```bash
# Windows (cmd)
set "DOUBAN_COOKIE=PASTE_YOUR_COOKIE_HERE"

# Windows (PowerShell)
$env:DOUBAN_COOKIE = 'PASTE_YOUR_COOKIE_HERE'

# macOS / Linux
export DOUBAN_COOKIE='PASTE_YOUR_COOKIE_HERE'
```

You can check whether the environment variable has been set successfully without printing the Cookie itself:

```bash
python -c "import os; print(bool(os.getenv('DOUBAN_COOKIE')))"
```

> ⚠️ **Security:** A Cookie may contain login/session credentials. Do not put it in your code, commit it to the repository, or share it with others. If a Cookie is accidentally exposed, log out of Douban or otherwise invalidate the session.

Run the tests:

```bash
python -m pytest
```

## Output

### `data/raw/`

Raw data, including original Douban user IDs.

| File               | Description                                     |
| ------------------ | ----------------------------------------------- |
| `ratings_raw.csv`  | `user_id, subject_id, rating`                   |
| `movies_raw.jsonl` | One movie per line: `subject_id, title, genres` |
| `users_done.txt`   | Completed users used for checkpoint/resume      |

### `data/processed/`

Cleaned and anonymized data.

| File          | Description                                                                          |
| ------------- | ------------------------------------------------------------------------------------ |
| `ratings.csv` | `user_id, movie_id, rating`, with ratings from 1 to 5                                |
| `movies.csv`  | `movie_id, subject_id, title, genres`, with genres stored as comma-separated strings |

Douban's textual rating labels are converted into numerical ratings:

* `力荐` → 5
* `推荐` → 4
* `还行` → 3
* `较差` → 2
* `很差` → 1

Reviews without an explicit rating are skipped.

The `process` command also outputs summary statistics. The following is an example of how filtering affects the sparsity of the rating matrix:

```text
# Without filtering:
python -m douban_crawler process

Users: 28, Movies: 279, Ratings: 385
Matrix density: 4.93% (sparsity: 95.07%)

# After filtering:
python -m douban_crawler process --min-user-ratings 3 --min-movie-ratings 2

Users: 14, Movies: 58, Ratings: 150
Matrix density: 18.47% (sparsity: 81.53%)
Rating distribution: {3: 6, 4: 85, 5: 59}
```

## Project Structure

```text
douban_crawler/
├── client.py        # HTTP client: rate limiting, retries, block detection
├── parsers.py       # Page parsing (pure functions)
├── crawler.py       # Crawling workflow and checkpoint/resume
├── pipeline.py      # Data cleaning, deduplication, and anonymization
└── __main__.py      # Command-line entry point

tests/
└── test_crawler.py
```

## Limitations

* **Login and browser verification**: Douban may trigger browser verification or restrict automated requests. A logged-in Cookie may be required in some access scenarios. The crawler therefore uses randomized delays, retries with exponential backoff, and stops when a verification page or access block is detected. The default request delay is 2–5 seconds, but this should **not** be considered a guaranteed safe rate. In practice, the appropriate crawling frequency may vary depending on the current access conditions. For larger crawling jobs, use a more conservative request rate and limit the size of individual runs.

* **Sparse data**: the crawler only collects ratings for movies that users have written reviews for, rather than all movies they have watched or rated. In my undergraduate thesis, this approach produced 1,909 ratings from 208 users across 1,283 movies, with a rating-matrix sparsity of 99.28%.

* **Rating bias**: in the example above, ratings of 4 and 5 account for 96% of the filtered dataset, with no ratings of 1 or 2. Possible reasons include the fact that users who choose to write reviews may be more likely to have strong or positive opinions, and that all users are sampled from the review section of the same seed movie, which may lead to correlated preferences. This bias should be considered when using the data to train recommendation models.

* **Dependency on page structure**: the XPath selectors depend on Douban's current HTML structure. Website changes may require updates to `parsers.py`.

## Disclaimer

This project is intended for learning purposes, including web scraping and data processing.

Please control the request frequency and collection scale, comply with Douban's applicable terms of service and `robots.txt`, and do not publicly redistribute the collected data or use it for commercial purposes.
