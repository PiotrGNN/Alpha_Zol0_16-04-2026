"""
News & Social Fetcher for ZoL0:
fetches crypto news and social posts (Twitter, Reddit, RSS).
"""

import requests
from typing import List, Dict, Optional


class NewsSocialFetcher:
    def __init__(self, twitter_bearer: Optional[str] = None):
        self.twitter_bearer = twitter_bearer

    def fetch_news(self, query: str = "crypto", limit: int = 20) -> List[Dict]:
        # Example: CryptoPanic API (free tier)
        url = (
            "https://cryptopanic.com/api/v1/posts/?auth_token=demo"
            "&currencies=BTC,ETH&public=true"
        )
        try:
            resp = requests.get(url)
            data = resp.json()
            return [
                {
                    "text": x["title"],
                    "source": x["source"]["title"],
                    "timestamp": x["published_at"],
                }
                for x in data.get("results", [])
            ][:limit]
        except Exception:
            return []

    def fetch_tweets(self, query: str = "bitcoin", limit: int = 20) -> List[Dict]:
        # Example: Twitter API v2 recent search (requires bearer token)
        if not self.twitter_bearer:
            return []
        url = (
            f"https://api.twitter.com/2/tweets/search/recent?query={query}"
            f"&max_results={min(limit, 100)}"
        )
        url += "&tweet.fields=author_id, created_at"
        headers = {"Authorization": f"Bearer {self.twitter_bearer}"}
        try:
            resp = requests.get(url, headers=headers)
            data = resp.json()
            return [
                {
                    "text": x["text"],
                    "author": x["author_id"],
                    "timestamp": x["created_at"],
                }
                for x in data.get("data", [])
            ]
        except Exception:
            return []

    def fetch_reddit(
        self, subreddit: str = "CryptoCurrency", limit: int = 20
    ) -> List[Dict]:
        url = f"https://www.reddit.com/r/{subreddit}/new.json?limit={limit}"
        headers = {"User-Agent": "zol0-bot/1.0"}
        try:
            resp = requests.get(url, headers=headers)
            data = resp.json()
            return [
                {
                    "text": x["data"]["title"],
                    "author": x["data"]["author"],
                    "timestamp": x["data"]["created_utc"],
                }
                for x in data["data"]["children"]
            ]
        except Exception:
            return []
