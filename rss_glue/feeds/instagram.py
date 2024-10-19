import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import pytz
import requests

from rss_glue import utils
from rss_glue.feeds import feed
from rss_glue.resources import global_config, utc_now

latest_version = 5


@dataclass
class InstagramPost(feed.FeedItem):
    """
    InstagramPost represents a single Instagram post's data.
    """

    image_src: str
    reel_src: Optional[str]
    album_src_list: Optional[list[str]]
    is_reel: bool
    is_multi: bool
    post_text: str

    def render(self) -> str:
        """
        Generate the HTML for a post
        """
        public_src = urljoin(
            global_config.base_url,
            global_config.file_cache.getRelativePath(self.id, "jpg", self.namespace).as_posix(),
        )
        return f"""
        <div class="post">
            <a href="{self.origin_url}">
                <img src="{public_src}" style="max-width: 100%; height: auto;" />
            </a>
            <p><b>{self.author}</b> {self.post_text}</p>
        </div>
        """

    def hashkey(self):
        return hash(self.id + self.title)


def randomMouseMovement(page):
    for _ in range(3):
        page.mouse.move(
            utils.rand_range(0, 500),
            utils.rand_range(0, 500),
            steps=utils.rand_range(5, 20),
        )
        page.wait_for_timeout(utils.rand_range(100, 500))


class InstagramFeed(feed.ScheduleFeed):
    """
    InstagramFeed turns an instagram user's feed into an RSS-able feed.
    """

    title_max_length = 80
    username: str
    limit: int
    # basePath = "https://www.piokok.com/profile/"
    basePath = "https://storynavigation.com/user-profile/"
    instaPath = "https://www.instagram.com/"
    name = "storynavigation"
    id_strftime_fmt = "%Y%m%d%H%M%S"
    post_cls: type[InstagramPost] = InstagramPost

    def __init__(self, username: str, limit: int = 6, schedule: str = "0 * * * *"):
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
        return self.post_cls(**cached)

    def cleanup(self):
        # Get a list of all the jpegs in the cache
        for file in global_config.file_cache.nsFiles("jpg", self.namespace):
            post_id = file.stem
            post = self.post(post_id)
            if not post:
                self.logger.info(f"removing post not found in cache {post_id} ")
                os.remove(file)

    def update(self, force=False):
        if not self.needs_update(force):
            return
        error_filepath = global_config.file_cache.getPath("error-screenshot", "png", self.namespace)
        page = global_config.page
        page.goto(self.origin_url)

        # Click the posts tab
        try:
            page.wait_for_load_state("networkidle", timeout=20000)

            # Force the page to load the garbage popup and close it.
            page.mouse.move(5, 5)
            page.mouse.click(5, 5)
            page.wait_for_timeout(utils.rand_range(200, 500))
            for _page in page.context.pages:
                if self.basePath not in _page.url:
                    _page.close()

            page.wait_for_timeout(utils.rand_range(1000, 2000))
            tabs = page.locator(".tabs-wrapper")
            tabs.wait_for(state="attached")
            post_btn = tabs.locator(".profile-publications__btn").first
            post_btn.scroll_into_view_if_needed()
            post_btn.click(force=True)
        except Exception as e:
            self.logger.error(f"{self.origin_url} could not find posts tab: account may not exist")
            page.screenshot(path=error_filepath)
            return

        page.wait_for_timeout(utils.rand_range(1000, 2000))
        page.wait_for_load_state("networkidle", timeout=20000)

        try:
            page.wait_for_selector(".posts .post-wrapper")
        except:
            self.logger.error(f"{self.origin_url} could not find page: account may not exist.")
            page.screenshot(path=error_filepath)
            return

        posts = page.locator(".posts .post-wrapper")
        self.logger.debug(f"found {posts.count()} posts")
        if posts.count() == 0:
            self.logger.error(f"{self.origin_url} unexpected: no posts found after 30 seconds")
            page.screenshot(path=error_filepath)
            return

        for i in range(min(self.limit, posts.count())):
            post = page.locator(".posts .post-wrapper").nth(i)
            post.scroll_into_view_if_needed()
            image_loc = post.locator("img[lazy='loaded']")
            image_loc.wait_for()
            image_src = image_loc.get_attribute("src")

            if image_src.startswith("data:image"):
                self.logger.error(f"{self.origin_url} skipping data:image post")
                page.screenshot(path=error_filepath)
                continue

            page.wait_for_timeout(utils.rand_range(500, 600))
            page.wait_for_load_state("networkidle")

            handle = post.element_handle()
            is_reel = handle.query_selector(".fa-video") is not None
            is_multi = handle.query_selector(".fa-clone") is not None
            # Time from first paragraph inside wrapper
            paragraphs = handle.query_selector_all("p")
            time_description = paragraphs[0].inner_text()
            posted_time = None

            try:
                # Example time: "15 October 2024 15:10:03"
                posted_time = datetime.strptime(time_description, "%d %B %Y %H:%M:%S")
                # Set timezome to UTC
                posted_time = posted_time.replace(tzinfo=pytz.utc)

            except ValueError as e:
                self.logger.error(
                    f"{self.origin_url} could not parse time: {time_description}: {str(e)}"
                )
                raise e

            post_short_id = posted_time.strftime(self.id_strftime_fmt)
            value = self.post(post_short_id)
            if value:
                self.logger.debug(f"cache hit for {value.title} {value.posted_time}")
                continue

            filename = global_config.file_cache.getPath(post_short_id, "jpg", self.namespace)
            try:
                r = requests.get(image_src, allow_redirects=True)
                r.raise_for_status()
                open(filename, "wb").write(r.content)
            except Exception as e:
                self.logger.error(f"{self.origin_url} could not download image: {str(e)}")
                page.screenshot(path=error_filepath)
                continue

            # Click the post to open the dialog
            post.click()
            post_text = page.locator(".modal-body .text-post p").nth(1).inner_text()
            title = f"Post by {self.author} at {time_description}"
            if post_text:
                title = post_text.strip()[: self.title_max_length]
                if len(post_text) > self.title_max_length:
                    title += "..."
                title = title.replace("\n", " ")

            if is_reel:
                try:
                    video = page.locator(".modal-body video")
                    video_src = video.first.get_attribute("src")
                except:
                    self.logger.error(f"{self.origin_url} could not find reel video src")
                    video_src = None

            # Close the modal by finding `aria-label="Close"`
            page.click('button[aria-label="Close"]')
            value = self.post_cls(
                **{
                    "version": latest_version,
                    "namespace": self.namespace,
                    "id": post_short_id,
                    "author": self.author,
                    "origin_url": urljoin(self.instaPath, self.username),
                    "title": title,
                    "post_text": post_text,
                    "discovered_time": utc_now(),
                    "posted_time": posted_time,  # override this below
                    "image_src": image_src,
                    "reel_src": video_src if is_reel else None,
                    "album_src_list": None,
                    "is_reel": is_reel,
                    "is_multi": is_multi,
                }
            )

            randomMouseMovement(page)

            self.logger.info(
                f'discovered reel={is_reel} multi={is_multi} id={post_short_id} time="{posted_time}" title="{title}"'
            )

            self.cache_set(value.id, value.to_dict())
        self.set_last_run()
