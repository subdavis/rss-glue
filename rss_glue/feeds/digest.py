from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from croniter import croniter

from rss_glue import utils
from rss_glue.feeds import feed
from rss_glue.resources import utc_now

latest_version = 0

digetst_post_template = """
<section>
    <a href="{origin_url}"><h3>{title}</h3></a>
    <time>{posted_time}</time>
    <div>{content}</div>
    <hr>
</section>
"""


@dataclass
class DigestPost(feed.FeedItem):
    """
    A digest post is like a periodical that contains
    content produced in a finite time period.

    :param id: <datetime_start>_<datetime_end>_<namespace>
    """

    subposts: list[feed.FeedItem]

    def render(self):
        html = "<p>"
        for post in self.subposts:
            html += digetst_post_template.format(
                title=post.title,
                content=post.render(),
                posted_time=post.posted_time.strftime(utils.human_strftime),
                origin_url=post.origin_url,
            )
        return html

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"subposts": [post.id for post in self.subposts]})
        return d

    @staticmethod
    def load(obj: dict, source: feed.BaseFeed):
        obj["subposts"] = [source.post(subpost_id) for subpost_id in obj["subposts"]]
        return DigestPost(**obj)


class DigestFeed(feed.BaseFeed):
    """
    A digest feed is a roll up of multiple feeds into one.
    """

    limit: int
    name = "digest"
    key_date_format = "%Y%m%d%H%M"
    schedule: str
    source: feed.BaseFeed

    def __init__(
        self,
        source: feed.BaseFeed,
        limit: int = 12,
        schedule: str = "0 * * * *",
        back_issues: int = 2,
    ):
        self.limit = limit
        self.source = source
        self.schedule = schedule
        self.title = f"Digest of {source.title}"
        self.author = source.author
        self.origin_url = source.origin_url
        self.back_issues = back_issues
        # if the source feed has a schedule, we should use that
        if hasattr(source, "schedule"):
            self.schedule = source.schedule
        super().__init__()

    @property
    def namespace(self):
        return f"{self.name}_{self.source.namespace}"

    def update(self, force: bool = False) -> int:
        """
        An update shall be needed if the last full period has passed
        and a digest post has not been created for it.
        """
        self.source.update(force)

        # Get the last full periodical interval
        itr = croniter(self.schedule, utc_now())
        period_start: datetime = itr.get_prev(datetime)
        new_issues = 0

        for _ in range(self.back_issues):
            period_end = period_start
            period_start = itr.get_prev(datetime)
            period_end_str = period_end.strftime(self.key_date_format)
            period_start_str = period_start.strftime(self.key_date_format)
            digest_id = f"{period_start_str}_{period_end_str}_{self.namespace}"

            # Check if the digest post has already been created
            if self.cache_get(digest_id):
                continue

            self.logger.debug(
                f" {self.namespace} requires_update for {digest_id} range {period_start} to {period_end}"
            )

            # Get all the source posts within the period
            source_posts = self.source.posts()
            posts_in_last_period = list(
                filter(
                    lambda post: post.posted_time >= period_start
                    and post.posted_time < period_end,
                    source_posts,
                )
            )
            if len(posts_in_last_period) > self.limit:
                self.logger.debug(
                    f" {len(posts_in_last_period)} posts in range, truncating to {self.limit}"
                )
            posts_in_last_period.sort(key=lambda post: post.score(), reverse=True)
            posts_in_last_period = posts_in_last_period[: self.limit]

            title = f"Issue {period_end.strftime(utils.human_strftime)}"
            value = DigestPost(
                version=0,
                namespace=self.namespace,
                id=digest_id,
                author="RSS Glue",
                origin_url="https://rssglue.com",
                title=title,
                discovered_time=period_end,
                posted_time=period_end,
                subposts=posts_in_last_period,
            )
            self.cache_set(value.id, value.to_dict())
            new_issues += 1
        return new_issues

    def post(self, post_id: str) -> Optional[feed.FeedItem]:
        cached = self.cache_get(post_id)
        if not cached:
            return None
        return DigestPost.load(cached, self.source)

    def posts(self) -> list[feed.FeedItem]:
        posts = super().posts()
        return [
            post
            for post in posts
            if isinstance(post, DigestPost) and len(post.subposts)
        ]
