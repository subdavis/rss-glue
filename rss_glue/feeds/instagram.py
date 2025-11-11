import html
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from rss_glue import utils
from rss_glue.feeds import feed
from rss_glue.resources import utc_now


@dataclass
class InstagramPost(feed.FeedItem):
    """
    An Instagram post from the scrapecreators API
    """

    html_template = utils.load_template("instagram_post.html.jinja")
    post_data: dict

    def likes(self) -> int:
        return self.post_data.get("like_count", 0)

    def comments(self) -> int:
        return self.post_data.get("comment_count", 0)

    def score(self) -> float:
        """Use like count as the score for sorting"""
        return float(self.likes())

    def render(self):
        # Extract caption text if available
        caption_text = None
        if caption := self.post_data.get("caption"):
            if text := caption.get("text", ""):
                caption_text = html.escape(text)

        # Extract music information if available
        music_info = None
        if music_metadata := self.post_data.get("music_metadata"):
            if music_info_data := music_metadata.get("music_info"):
                if music_asset_info := music_info_data.get("music_asset_info"):
                    title = music_asset_info.get("title")
                    artist = music_asset_info.get("display_artist")
                    if title and artist:
                        music_info = f"{html.escape(title)} - {html.escape(artist)}"
                    elif title:
                        music_info = html.escape(title)

        return self.html_template.render(
            author=self.author,
            likes=self.likes(),
            comments=self.comments(),
            media_type=self.post_data.get("media_type"),
            image_versions=self.post_data.get("image_versions2", {}).get("candidates"),
            video_versions=self.post_data.get("video_versions"),
            carousel_media=self.post_data.get("carousel_media"),
            caption_text=caption_text,
            music_info=music_info,
        )


class InstagramFeed(feed.ThrottleFeed):
    """
    An Instagram feed via the scrapecreators API
    """

    username: str
    url: str
    api_key: str
    post_cls: type[InstagramPost] = InstagramPost
    name: str = "instagram"

    def __init__(
        self,
        username: str,
        api_key: str,
        interval: timedelta = timedelta(hours=6),
    ):
        self.username = username
        self.api_key = api_key
        self.url = f"https://api.scrapecreators.com/v2/instagram/user/posts?handle={username}"
        self.title = f"@{username}"
        self.author = username
        self.origin_url = f"https://www.instagram.com/{username}"
        super().__init__(interval=interval)

    @property
    def namespace(self):
        return f"instagram_{self.username}"

    def update(self):

        # Fetch posts from the scrapecreators API
        session = utils.make_browser_session()
        headers = {"x-api-key": self.api_key}
        response = session.get(self.url, headers=headers)
        response.raise_for_status()
        data = response.json()

        posts = data.get("items", [])
        for post_data in posts:
            post_id = post_data.get("id") or post_data.get("pk")
            if not post_id:
                self.logger.warning("Post missing ID, skipping")
                continue

            post_id = str(post_id)

            if self.cache_get(post_id):
                continue

            # Extract timestamp
            taken_at = post_data.get("taken_at")
            if taken_at:
                created_time = datetime.fromtimestamp(taken_at, tz=timezone.utc)
            else:
                created_time = utc_now()

            # Extract author
            author = self.username
            if user := post_data.get("user"):
                author = user.get("username", self.username)

            # Extract title from caption
            title = "Instagram Post"
            if caption := post_data.get("caption"):
                caption_text = caption.get("text", "")
                # Use first line or first 100 chars as title
                title = caption_text.split("\n")[0][:100]

            # Build post URL
            code = post_data.get("code")
            post_url = f"https://www.instagram.com/p/{code}/" if code else self.origin_url

            value = self.post_cls(
                version=0,
                namespace=self.namespace,
                id=post_id,
                post_data=post_data,
                author=author,
                title=title,
                posted_time=created_time,
                discovered_time=utc_now(),
                origin_url=post_url,
                enclosure=None,
            )
            self.logger.info(f"Adding post {value.id}")
            self.cache_set(post_id, value.to_dict())

        self.set_last_run()
