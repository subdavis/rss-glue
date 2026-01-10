"""RSS XML generation."""
from datetime import datetime, timezone

from feedgen.feed import FeedGenerator
from sqlmodel import Session, select

from rss_glue.models.db import Feed, Post
from rss_glue.feeds.merge import MergeFeedHandler
from rss_glue.feeds.digest import DigestFeedHandler


def format_digest_issue_content(posts: list[Post], base_url: str) -> str:
    """Generate HTML content for a digest issue containing links to posts."""
    if not posts:
        return "<p>No posts in this digest period.</p>"

    lines = ["<ul>"]
    for post in posts:
        author_str = f" - {post.author}" if post.author else ""
        lines.append(
            f'<li><a href="{post.link}">{post.title}</a>{author_str}</li>'
        )
    lines.append("</ul>")
    return "\n".join(lines)


def generate_rss(feed_id: str, session: Session, base_url: str) -> str:
    """Generate RSS XML for a feed."""
    feed = session.get(Feed, feed_id)
    if not feed:
        raise ValueError(f"Feed not found: {feed_id}")

    fg = FeedGenerator()
    fg.title(feed.name)
    fg.link(href=f"{base_url}feed/{feed_id}/rss", rel="self")
    fg.description(f"RSS feed: {feed.name}")
    fg.lastBuildDate(datetime.now(timezone.utc))

    # Handle different feed types
    if feed.type == "digest":
        # Digest feeds output issues as items
        issues = DigestFeedHandler.get_digest_issues(feed_id, feed.limit, session)

        for issue in issues:
            posts = DigestFeedHandler.get_issue_posts(issue.id, session)
            entry = fg.add_entry()

            # Format the title with date range
            start_str = issue.period_start.strftime("%b %d")
            end_str = issue.period_end.strftime("%b %d, %Y")
            entry.title(f"{feed.name}: {start_str} - {end_str}")

            # Link to the feed's RSS
            entry.link(href=f"{base_url}feed/{feed_id}/rss")

            # Unique ID for this digest issue
            entry.guid(f"digest:{feed_id}:{issue.id}", permalink=False)

            # Content is a list of links to the included posts
            content = format_digest_issue_content(posts, base_url)
            entry.description(content)

            # Publish date is the period end
            # Ensure timezone awareness for feedgen
            pub_date = issue.period_end
            if pub_date.tzinfo is None:
                pub_date = pub_date.replace(tzinfo=timezone.utc)
            entry.pubDate(pub_date)
    else:
        # Get posts based on feed type
        if feed.type == "merge":
            posts = MergeFeedHandler.get_merged_posts(feed_id, feed.limit, session)
        else:
            stmt = (
                select(Post)
                .where(Post.feed_id == feed_id)
                .order_by(Post.published_at.desc())
                .limit(feed.limit)
            )
            posts = list(session.exec(stmt).all())

        for post in posts:
            entry = fg.add_entry()
            entry.title(post.title)
            entry.link(href=post.link)
            entry.guid(f"{post.feed_id}:{post.external_id}", permalink=False)

            if post.content:
                entry.description(post.content)

            if post.author:
                entry.author(name=post.author)

            # Ensure timezone awareness for feedgen
            pub_date = post.published_at
            if pub_date.tzinfo is None:
                pub_date = pub_date.replace(tzinfo=timezone.utc)
            entry.pubDate(pub_date)

    return fg.rss_str(pretty=True).decode("utf-8")
