from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from croniter import croniter

from rss_glue import utils
from rss_glue.feeds import feed
from rss_glue.resources import global_config, utc_now

latest_version = 0

digetst_post_template = utils.load_template("digest_post.html.jinja")


@dataclass
class DigestPost(feed.FeedItem):
    """
    A digest post is like a periodical that contains
    content produced in a finite time period.

    :param id: <datetime_start>_<datetime_end>_<namespace>
    """

    subposts: list[feed.FeedItem]

    def __post_init__(self):
        if len(self.subposts) > 0 and type(self.subposts[0]) is dict:
            resolved_subposts = []
            for subpost in self.subposts:
                subpost_source = global_config.by_namespace(subpost.get("namespace"))
                subpost_id = subpost.get("id")
                if subpost_source and subpost_id:
                    resolved_post = subpost_source.post(subpost_id)
                    if resolved_post:
                        resolved_subposts.append(resolved_post)
            self.subposts = resolved_subposts
        return super().__post_init__()

    def render(self):
        html = ""
        for post in self.subposts:
            html += digetst_post_template.render(
                title=post.title,
                content=post.render(),
                posted_time=post.posted_time.strftime(utils.human_strftime),
                origin_url=post.origin_url,
            )
        return html

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update(
            {"subposts": [{"namespace": post.namespace, "id": post.id} for post in self.subposts]}
        )
        return d


class DigestFeed(feed.BaseFeed):
    """
    A digest feed is a roll up of multiple feeds into one.
    """

    limit: int
    name = "digest"
    key_date_format = "%Y%m%d%H%M"
    schedule: str
    source: feed.BaseFeed
    post_cls: type[DigestPost] = DigestPost

    def __init__(
        self,
        source: feed.BaseFeed,
        limit: int = 12,
        schedule: str = "0 0 * * *",
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

    def sources(self) -> Iterable[feed.BaseFeed]:
        """
        Special case: Hide the source from normal source collection
        since this class will take responsibility for updating it.
        """
        yield self.source

    def missing_issues(self) -> list[tuple[datetime, datetime, str]]:
        """
        Get a list of missing digest issues that need to be created.
        Returns a list of tuples: (period_start, period_end, digest_id)
        The list is ordered from most recent to oldest, up to back_issues count.
        """
        missing = []
        itr = croniter(self.schedule, utc_now())
        period_start: datetime = itr.get_prev(datetime)

        for index in range(self.back_issues):
            period_end = period_start
            period_start = itr.get_prev(datetime)
            period_end_str = period_end.strftime(self.key_date_format)
            period_start_str = period_start.strftime(self.key_date_format)
            digest_id = f"{period_start_str}_{period_end_str}_{self.namespace}"

            # Check if the digest post has already been created
            if not self.cache_get(digest_id):
                missing.append((period_start, period_end, digest_id))

        return missing

    def update(self):
        """
        An update shall be needed if the last full period has passed
        and a digest post has not been created for it.
        """
        for index, (period_start, period_end, digest_id) in enumerate(self.missing_issues()):
            self.logger.debug(
                f" {self.namespace} requires_update for {digest_id} range {period_start} to {period_end}"
            )

            if index == 0:
                # Force the source to update, but only for the latest period, not back issues
                # WARNING: if a source is used in multiple DigestFeeds, this could cause redundant updates
                # But digests are expected to be rare enough that this should be acceptable
                self.source.update()

            # Get all the source posts within the period using time range filtering
            posts_in_last_period = self.source.posts(start=period_start, end=period_end)

            self.logger.info(
                f" Found {len(posts_in_last_period)} posts in period {period_start} to {period_end}"
            )

            if len(posts_in_last_period) > self.limit:
                self.logger.debug(
                    f" {len(posts_in_last_period)} posts in range, truncating to {self.limit}"
                )
            posts_in_last_period.sort(key=lambda post: post.score(), reverse=True)
            posts_in_last_period = posts_in_last_period[: self.limit]

            title = f"Issue {period_end.strftime(utils.human_strftime)}"
            value = self.post_cls(
                version=0,
                namespace=self.namespace,
                id=digest_id,
                author="RSS Glue",
                origin_url=self.origin_url,
                title=title,
                discovered_time=period_end,
                posted_time=period_end,
                subposts=posts_in_last_period,
                enclosure=None,
            )
            self.logger.info(f"Adding digest post {value.id} for {period_end}")
            self.cache_set(value.id, value.to_dict())

    def posts(
        self, limit: int = 50, start: Optional[datetime] = None, end: Optional[datetime] = None
    ) -> list[feed.FeedItem]:
        posts = super().posts(limit=limit, start=start, end=end)
        return [post for post in posts if isinstance(post, self.post_cls) and len(post.subposts)]

    def next_update(self, force: bool) -> tuple[Optional[datetime], bool]:
        """
        Return the next time this digest should be updated and whether it needs updating now.
        Returns the end time of the oldest missing issue, or the next scheduled time if none are missing.
        The returned time may be in the past if there are missing issues.
        """
        if self.locked and not force:
            self.logger.warning("Feed is locked - skipping update (use force=True to override)")
            return None, False

        missing = self.missing_issues()
        if len(missing) > 0:
            oldest_missing = min([period_end for _, period_end, _ in missing])
            return oldest_missing, True

        # No missing issues, return the next scheduled time
        itr = croniter(self.schedule, utc_now())
        next_scheduled = itr.get_next(datetime)
        return next_scheduled, False
