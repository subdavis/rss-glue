import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional
from urllib.parse import urljoin

import pytz
import requests
from instagrapi import Client

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


class InstagramFeed(feed.ThrottleFeed):
    """
    InstagramFeed turns an instagram user's feed into an RSS-able feed.
    """

    title_max_length = 80
    username: str
    limit: int
    instaPath = "https://www.instagram.com/"
    name = "instagram"
    id_strftime_fmt = "%Y%m%d%H%M%S"
    post_cls: type[InstagramPost] = InstagramPost

    def __init__(
        self,
        username: str,
        limit: int = 6,
        interval: timedelta = timedelta(days=1),
        client: Client = None,
    ):
        self.username = username
        self.limit = limit
        self.title = f"Instagram @{username}"
        self.author = f"@{username}"
        self.origin_url = urljoin(self.instaPath, self.username)
        self.cl = client
        super().__init__(interval=interval)

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

        user_id = self.meta.get("user_id", None)
        if not user_id:
            user_id = self.cl.user_id_from_username(self.username)
        self.meta = {"user_id": user_id}
        self.logger.debug(f"found user_id {user_id}")
        posts = self.cl.user_medias(user_id, self.limit)
        self.logger.debug(f"found {len(posts)} posts")

        print(posts)

        for i in range(min(self.limit, len(posts))):
            post = posts[i]

            resources = post.resources

            image_src = str(post.thumbnail_url or resources[0].thumbnail_url)
            is_reel = post.media_type == 2
            is_multi = post.media_type == 8
            posted_time = post.taken_at
            posted_time = posted_time.replace(tzinfo=pytz.utc)
            post_short_id = post.pk

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
                continue

            post_text = post.caption_text
            title = f"Post by {self.author} at {posted_time.strftime(utils.human_strftime)}"
            if post_text:
                title = post_text.strip()[: self.title_max_length]
                if len(post_text) > self.title_max_length:
                    title += "..."
                title = title.replace("\n", " ")

            if is_reel:
                try:
                    video_src = str(post.video_url or post.resources[0].video_url)
                except:
                    self.logger.error(f"{self.origin_url} could not find reel video src")
                    video_src = None

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

            self.logger.info(
                f'discovered reel={is_reel} multi={is_multi} id={post_short_id} time="{posted_time}" title="{title}"'
            )

            self.cache_set(value.id, value.to_dict())
        self.set_last_run()
