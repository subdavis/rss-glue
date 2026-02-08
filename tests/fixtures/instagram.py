"""Sample Instagram API responses for testing."""

# A minimal but realistic ScrapeCreators API response
# covering the three media types: single image, carousel, and video.
INSTAGRAM_API_RESPONSE = {
    "items": [
        # Post 1: Single image with caption and music
        {
            "id": "3001234567890123456",
            "pk": "3001234567890123456",
            "code": "CxABCDEfgh1",
            "taken_at": 1700000000,  # 2023-11-14T22:13:20Z
            "media_type": 1,
            "caption": {
                "text": "Golden hour at the beach\nSunset vibes only",
            },
            "like_count": 4200,
            "comment_count": 87,
            "user": {"username": "testuser"},
            "image_versions2": {
                "candidates": [
                    {"url": "https://cdn.instagram.com/image1_full.jpg", "width": 1080},
                    {"url": "https://cdn.instagram.com/image1_thumb.jpg", "width": 320},
                ]
            },
            "music_metadata": {
                "music_info": {
                    "music_asset_info": {
                        "title": "Summer Breeze",
                        "display_artist": "DJ Chill",
                    }
                }
            },
        },
        # Post 2: Carousel with 3 images
        {
            "id": "3009876543210987654",
            "pk": "3009876543210987654",
            "code": "CxZYXWVUts2",
            "taken_at": 1699900000,  # 2023-11-13T18:26:40Z
            "media_type": 8,
            "caption": {
                "text": "Trip highlights from last week",
            },
            "like_count": 1500,
            "comment_count": 42,
            "user": {"username": "testuser"},
            "carousel_media": [
                {
                    "image_versions2": {
                        "candidates": [
                            {"url": "https://cdn.instagram.com/carousel_1.jpg", "width": 1080},
                        ]
                    }
                },
                {
                    "image_versions2": {
                        "candidates": [
                            {"url": "https://cdn.instagram.com/carousel_2.jpg", "width": 1080},
                        ]
                    }
                },
                {
                    "image_versions2": {
                        "candidates": [
                            {"url": "https://cdn.instagram.com/carousel_3.jpg", "width": 1080},
                        ]
                    }
                },
            ],
        },
        # Post 3: Video post
        {
            "id": "3005555555555555555",
            "pk": "3005555555555555555",
            "code": "CxMNOPQRst3",
            "taken_at": 1699800000,  # 2023-11-12T14:40:00Z
            "media_type": 2,
            "caption": None,
            "like_count": 890,
            "comment_count": 15,
            "user": {"username": "testuser"},
            "video_versions": [
                {"url": "https://cdn.instagram.com/video1.mp4", "width": 1080},
            ],
            "image_versions2": {
                "candidates": [
                    {"url": "https://cdn.instagram.com/video1_poster.jpg", "width": 1080},
                ]
            },
        },
    ]
}
