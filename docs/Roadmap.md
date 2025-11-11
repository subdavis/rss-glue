## Problem: Image download failures cause infinite retries

Images that fail to download will be retried every generate cycle. It's not a huge problem, but it would be better to limit the number of retries per image.

## Problem: Image cache is broken by namespace so images in different feeds are duplicated

Fix the file cache so that images are only stored once, even if they are used in multiple feeds.

## Generate example usages

* Changing the rendering of a feed item
* Changing the rendering of a specific Instagram Feed Item
* Appending expensive metadata to a feed item (e.g., fetching article `og` metadata)
* Building an apprise notification from new feed items
* Building a digest of a merge of multiple feeds