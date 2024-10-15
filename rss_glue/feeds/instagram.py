from dataclasses import dataclass
from datetime import timedelta
from typing import Optional
from urllib.parse import urljoin
from urllib.request import urlretrieve

from rss_glue.feeds import feed
from rss_glue.logger import logger
from rss_glue.resources import global_config, utc_now

latest_version = 3


@dataclass
class InstagramPost(feed.FeedItem):
    """
    InstagramPost represents a single Instagram post's data.
    """

    image_src: str
    is_reel: bool
    is_multi: bool
    post_text: str

    def render(self) -> str:
        """
        Generate the HTML for a post
        """
        public_src = urljoin(
            global_config.base_url,
            global_config.file_cache.getRelativePath(
                self.id, "jpg", self.namespace
            ).as_posix(),
        )
        return f"""
        <div class="post">
            <a href="{self.origin_url}">
                <img src="{public_src}" style="max-width: 100%; height: auto;" />
            </a>
            <p><b>{self.author}</b> {self.post_text}</p>
        </div>
        """


class InstagramFeed(feed.ScheduleFeed):
    """
    InstagramFeed turns an instagram user's feed into an RSS-able feed.
    """

    title_max_length = 80
    username: str
    limit: int
    basePath = "https://www.piokok.com/profile/"
    name = "piokok"

    def __init__(self, username: str, limit: int = 12, schedule: str = "0 * * * *"):
        self.username = username
        self.limit = limit
        self.title = f"Instagram @{username}"
        self.author = f"@{username}"
        self.origin_url = urljoin(self.basePath, self.username)
        super().__init__(schedule=schedule)

    @property
    def namespace(self):
        return f"{self.name}_{self.username}"

    def post(self, post_id) -> Optional[InstagramPost]:
        cached = self.cache_get(post_id)
        if not cached:
            return None
        if cached.get("post_html", None) is not None:
            del cached["post_html"]
        cached["author"] = self.author
        cached["title"] = cached["post_text"][: self.title_max_length] + "..."
        return InstagramPost(**cached)

    def update(self, force=False) -> int:
        if not self.needs_update(force):
            return 0
        page = global_config.page
        page.goto(self.origin_url)
        new_posts = []
        posts = page.locator(".posts .items .item").element_handles()
        logger.debug(f"   found {len(posts)} posts")
        for post in posts[: self.limit]:
            post_link = post.query_selector("a.cover_link").get_attribute("href")

            value = self.post(post_link)
            if value:
                logger.debug(f"   cache hit for {value.id}")
                continue

            post.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            page.wait_for_load_state("networkidle")
            image = post.query_selector("img.lazyloaded")
            image_src = image.get_attribute("src")
            is_reel = post.query_selector(".corner .icon_video") is not None
            is_multi = post.query_selector(".corner .icon_multi") is not None
            time_description = post.query_selector(".time .txt").inner_text()
            post_text = image.get_attribute("alt")
            urlretrieve(
                image_src,
                global_config.file_cache.getPath(post_link, "jpg", self.namespace),
            )

            value = InstagramPost(
                **{
                    "version": latest_version,
                    "namespace": self.namespace,
                    "id": post_link,
                    "author": self.author,
                    "origin_url": urljoin(self.origin_url, post_link),
                    "title": post_text.strip()[: self.title_max_length] + "...",
                    "post_text": post_text,
                    "discovered_time": utc_now(),
                    "posted_time": utc_now(),  # override this below
                    "image_src": image_src,
                    "is_reel": is_reel,
                    "is_multi": is_multi,
                }
            )

            ## parse "N days/weeks/months ago" into a real date
            try:
                units_ago = int(time_description.split(" ")[0])
                if "days ago" in time_description or "day ago" in time_description:
                    value.posted_time = utc_now() - timedelta(days=units_ago)
                elif "weeks ago" in time_description or "week ago" in time_description:
                    value.posted_time = utc_now() - timedelta(weeks=units_ago)
                elif (
                    "months ago" in time_description or "month ago" in time_description
                ):
                    value.posted_time = utc_now() - timedelta(days=units_ago * 30)
                elif "hours ago" in time_description or "hour ago" in time_description:
                    value.posted_time = utc_now() - timedelta(hours=units_ago)
                elif "years ago" in time_description or "year ago" in time_description:
                    value.posted_time = utc_now() - timedelta(days=units_ago * 365)
                elif (
                    "minutes ago" in time_description
                    or "minute ago" in time_description
                ):
                    value.posted_time = utc_now() - timedelta(minutes=units_ago)
                else:
                    raise ValueError(f"Unknown time description: {time_description}")
                logger.debug(
                    f"   inferred time: {value.posted_time} from '{time_description}'"
                )
            except:
                logger.error(f"   could not parse time: {time_description}")
                pass

            logger.debug(f"   cache miss for {post_link}")

            if is_reel:
                self._get_reel_details(post_link, value)
            elif is_multi:
                self._get_album_details(post_link, value)

            self.cache_set(value.id, value.to_dict())
            new_posts.append(value)

        self.set_last_run()
        return len(new_posts)

    def _get_album_details(self, post_url: str, post: InstagramPost):
        """ """
        pass

    def _get_reel_details(self, post_url: str, post: InstagramPost):
        """
        For album posts and reel posts
        """
        pass
