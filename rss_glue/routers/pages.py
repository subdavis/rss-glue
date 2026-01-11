"""HTML page routes."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, func

from rss_glue.database import get_session
from rss_glue.models.db import Feed, MediaCache, Post
from rss_glue.services.config_sync import get_current_config

router = APIRouter()

templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@router.get("/")
def index(request: Request, session: Session = Depends(get_session)):
    """List all feeds."""
    feeds = list(session.exec(select(Feed)).all())
    return templates.TemplateResponse(
        "index.html", {"request": request, "feeds": feeds}
    )


@router.get("/config")
def config_page(request: Request, session: Session = Depends(get_session)):
    """Config editor page."""
    config = get_current_config(session)
    feeds_json = json.dumps(config["feeds"], indent=2)
    return templates.TemplateResponse(
        "config.html",
        {
            "request": request,
            "config": config,
            "feeds_json": feeds_json,
            "error": None,
        },
    )


@router.get("/gallery")
def gallery_page(
    request: Request, page: int = 1, session: Session = Depends(get_session)
):
    """Gallery page showing all media images in reverse chronological order."""
    if page < 1:
        page = 1

    images_per_page = 50
    offset = (page - 1) * images_per_page

    # Get total count for pagination (only images)
    total_count = (
        session.exec(
            select(func.count(MediaCache.id)).where(
                MediaCache.content_type.like("image/%")
            )
        ).first()
        or 0
    )
    total_pages = (total_count + images_per_page - 1) // images_per_page

    # Get paginated media records in reverse chronological order by post published time
    media_records = session.exec(
        select(MediaCache, Feed, Post)
        .join(Feed, MediaCache.feed_id == Feed.id)
        .join(Post, MediaCache.post_id == Post.id)
        .where(MediaCache.content_type.like("image/%"))  # Only images
        .order_by(Post.published_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(images_per_page)
    ).all()

    # Convert to list of dictionaries for template
    gallery_data = []
    for media, feed, post in media_records:
        # Build media URL from local_path
        # Format: /media/{hash_prefix}/{filename}
        path_parts = media.local_path.split("/")
        if len(path_parts) >= 2:
            hash_prefix = path_parts[-2]
            filename = path_parts[-1]
            media_url = f"/media/{hash_prefix}/{filename}"
        else:
            # Fallback if path format is unexpected
            media_url = f"/media/{media.local_path}"

        gallery_data.append(
            {"media": media, "feed": feed, "post": post, "media_url": media_url}
        )

    return templates.TemplateResponse(
        "gallery.html",
        {
            "request": request,
            "gallery_data": gallery_data,
            "current_page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "prev_page": page - 1 if page > 1 else None,
            "next_page": page + 1 if page < total_pages else None,
        },
    )
