"""
Sentiment Analysis Strategy for ZoL0:
AI/NLP-driven trading on social/news sentiment.
"""

from typing import Any, Dict, List, Optional
from .base import Strategy
import logging
from utils.news_social_fetcher import NewsSocialFetcher

logger = logging.getLogger(__name__)


class SentimentStrategy(Strategy):

    def calculate_position_size(self, signal: dict, account_balance: float) -> float:
        """
        Calculate position size for sentiment strategy.
        Uses min_confidence as a fraction or defaults to 0.05.
        """
        fraction = self.parameters.get("min_confidence", 0.05)
        return float(account_balance) * min(0.5, max(0.01, fraction))

    def __init__(
        self,
        name: str = "SentimentStrategy",
        sentiment_model=None,
        influencer_list: Optional[List[str]] = None,
        min_confidence: float = 0.8,
        min_mentions: int = 100,
        parameters: Optional[Dict[str, Any]] = None,
    ):
        if parameters is None:
            parameters = {
                "min_confidence": min_confidence,
                "min_mentions": min_mentions,
            }
        super().__init__(name=name, timeframes=["1m", "5m", "1h"])
        # callable(text) -> (score, label)
        self.sentiment_model = sentiment_model
        self.influencer_list = influencer_list or []
        self.parameters = parameters
        self.last_signal = None

    def analyze(
        self,
        symbol: str,
        sentiment_data: List[Dict[str, Any]],
        technical_signal: Optional[Dict[str, Any]] = None,
        raw_texts: Optional[List[str]] = None,
        fetch_news: bool = False,
        fetch_twitter: bool = False,
        fetch_reddit: bool = False,
        news_query: str = "crypto",
        twitter_query: str = "bitcoin",
        reddit_sub: str = "CryptoCurrency",
        fetcher: Optional[NewsSocialFetcher] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Analyze aggregated sentiment data and generate trading signals.
        Optionally, run NLP model on raw_texts or auto-fetch news/social.
        Args:
            symbol (str): Trading symbol.
            sentiment_data (List[Dict]):
                List of dicts with keys:
                'text', 'score', 'label', 'source', 'timestamp', 'author'.
            technical_signal (Optional[Dict]):
                Optional technical signal to combine with sentiment.
            raw_texts (Optional[List[str]]):
                Raw texts to analyze with NLP model.
            fetch_news, fetch_twitter, fetch_reddit: If True, auto-fetch data.
            fetcher (Optional[NewsSocialFetcher]): Fetcher instance.
        Returns:
            Dict[str, Any]: Analysis results with signals and metrics.
        """
        # Auto-fetch news/social if requested
        if fetcher:
            if fetch_news:
                news = fetcher.fetch_news(query=news_query)
                if news:
                    if not raw_texts:
                        raw_texts = []
                    raw_texts += [x["text"] for x in news]
            if fetch_twitter:
                tweets = fetcher.fetch_tweets(query=twitter_query)
                if tweets:
                    if not raw_texts:
                        raw_texts = []
                    raw_texts += [x["text"] for x in tweets]
            if fetch_reddit:
                posts = fetcher.fetch_reddit(subreddit=reddit_sub)
                if posts:
                    if not raw_texts:
                        raw_texts = []
                    raw_texts += [x["text"] for x in posts]
        # If raw_texts provided, run NLP model and aggregate
        if raw_texts and self.sentiment_model:
            sentiment_data = []
            for text in raw_texts:
                score, label = self.sentiment_model.predict(text)
                sentiment_data.append(
                    {
                        "text": text,
                        "score": score,
                        "label": label,
                        "source": "raw",
                        "author": "",
                        "timestamp": None,
                    }
                )
        min_conf = self.parameters.get("min_confidence", 0.8)
        min_mentions = self.parameters.get("min_mentions", 100)
        influencer_weight = 2.0
        pos, neg, neu, total, weighted_score = 0, 0, 0, 0, 0.0
        influencer_mentions = 0
        for item in sentiment_data:
            score = item.get("score", 0)
            label = item.get("label", "neutral")
            author = item.get("author", "")
            weight = influencer_weight if author in self.influencer_list else 1.0
            if label == "positive":
                pos += 1 * weight
                weighted_score += score * weight
            elif label == "negative":
                neg += 1 * weight
                weighted_score += score * weight
            else:
                neu += 1 * weight
            if author in self.influencer_list:
                influencer_mentions += 1
            total += 1 * weight
        avg_score = weighted_score / max(total, 1)
        pos_ratio = pos / max(total, 1)
        neg_ratio = neg / max(total, 1)
        # Decision logic
        signal = None
        if total >= min_mentions and avg_score > min_conf and pos_ratio > 0.7:
            signal = {
                "type": "entry",
                "side": "buy",
                "reason": "strong_positive_sentiment",
                "avg_score": avg_score,
                "pos_ratio": pos_ratio,
                "influencer_mentions": influencer_mentions,
            }
        elif total >= min_mentions and avg_score < -min_conf and neg_ratio > 0.7:
            signal = {
                "type": "entry",
                "side": "sell",
                "reason": "strong_negative_sentiment",
                "avg_score": avg_score,
                "neg_ratio": neg_ratio,
                "influencer_mentions": influencer_mentions,
            }
        elif technical_signal and signal:
            # Combine with technicals: only act if both agree
            if technical_signal.get("side") == signal.get("side"):
                signal["reason"] += "+technical_confirmed"
            else:
                signal = None
        if signal:
            self.last_signal = signal["type"]
        return {
            "signals": [signal] if signal else [],
            "metrics": {
                "avg_score": avg_score,
                "pos_ratio": pos_ratio,
                "neg_ratio": neg_ratio,
                "total": total,
                "influencer_mentions": influencer_mentions,
            },
        }
