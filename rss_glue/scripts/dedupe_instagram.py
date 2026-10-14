"""One-shot cleanup for the Instagram duplicate posts.

ScrapeCreators changed `items[].id` from "{pk}_{user_pk}" to "POLARIS_{pk}",
which gave every post a new external_id, so one fetch re-added the whole feed
with "now" timestamps and no images. The handler now derives the id from
pk + user pk again, so the stale copies just need deleting: for each
(feed, link) pair keep the earliest-published post, drop the rest.

    uv run python -m rss_glue.scripts.dedupe_instagram          # dry run
    uv run python -m rss_glue.scripts.dedupe_instagram --commit
"""

import sys

from sqlmodel import Session, select

from rss_glue.handlers.digest import DigestIssuePost
from rss_glue.models.db import Feed, Post
from rss_glue.database import engine


def main() -> None:
    commit = "--commit" in sys.argv

    with Session(engine) as session:
        feed_ids = session.exec(select(Feed.id).where(Feed.type == "instagram")).all()

        doomed: list[Post] = []
        for feed_id in feed_ids:
            posts = session.exec(
                select(Post).where(Post.feed_id == feed_id).order_by(Post.published_at)  # type: ignore[arg-type]
            ).all()
            seen: set[str] = set()
            for post in posts:
                if post.link in seen:
                    doomed.append(post)
                else:
                    seen.add(post.link)

        for post in doomed:
            print(f"{post.feed_id}\t{post.published_at:%Y-%m-%d %H:%M}\t{post.link}")

            for link in session.exec(
                select(DigestIssuePost).where(DigestIssuePost.post_id == post.id)
            ).all():
                session.delete(link)
            session.delete(post)

        print(f"\n{len(doomed)} duplicate posts across {len(feed_ids)} instagram feeds")
        if commit:
            session.commit()
            print("deleted")
        else:
            print("dry run, pass --commit to delete")


if __name__ == "__main__":
    main()
