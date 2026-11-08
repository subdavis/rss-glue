"""Strip recipient-personalized links (one-click unsubscribe etc.) from stored email posts.

New posts are cleaned by EmailFeedHandler.process_post_content; this applies
the same redaction to posts stored before it existed.
"""

from sqlmodel import Session, select

from rss_glue.models.db import Feed, Post
from rss_glue.services.imap_inbox import redact_recipient


def migrate(engine):
    with Session(engine) as session:
        for feed in session.exec(select(Feed).where(Feed.type == "email")).all():
            address = (feed.config or {}).get("address")
            if not address:
                continue
            for post in session.exec(select(Post).where(Post.feed_id == feed.id)).all():
                cleaned = redact_recipient(post.content, address)
                if cleaned != post.content:
                    post.content = cleaned
                    session.add(post)
        session.commit()
