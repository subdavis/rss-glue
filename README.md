# RSS Glue

RSS Glue is a highly extensible, filesystem-based RSS/Atom feed generator and manipulator. Build digests, merge feeds, and use AI tools to make your RSS feed work for you!

<img src='./docs/images/glue.webp' width=300 style='border-radius: 10px' />

## Inspiration

* [Kill the newsletter](https://kill-the-newsletter.com/)
* [Rsshub](https://docs.rsshub.app/)
* [Zapier](https://zapier.com/)

## Features

External Data Sources

* `RssFeed` is a data source using an external RSS Feed.
* `InstagramFeed` is a data source using an instagram profile via Piokok.

Meta Data Sources

* `MergeFeed` is a simple chronological merge of multiple feeds.
* `DigestFeed` is a periodical rollup of a feed, such as a daily digest.
* `AiFilterFeed` is a feed filtered by a prompt to some AI backend.

Outputs

* `RssOutput` is an output RSS feed.
* `HTMLOutput` is a very basic single page web feed output.
* `HTMLIndexOutput` is a meta-output HTML page with a link to all its child outputs. Handy for quick reference and adding feeds to your RSS reader.

## Quick Start

```bash
# Install RSS Glue
pip install rss-glue

# Install the static dependencies like the playwright browser
playwright install
rss-glue install

# Create your configuration file and edit it
touch config.py

# Then generate your feed
rss-glue --config config.py update
# Or start a long-running process
rss-glue --config config.py watch
# Or start the debug web server
rss-glue --config config.py debug
```

## Configuration

RSS Glue is configured entirely with Python. Here's an example.

```python
from rss_glue.feeds import DigestFeed, InstagramFeed, MergeFeed, RssFeed
from rss_glue.outputs import HTMLIndexOutput, HtmlOutput, RssOutput
from rss_glue.resources import global_config

# An optional function to run after content has been generated
# def run_after_generate():
#     import subprocess
#     subprocess.run(["rsync", "/etc/rssglue/static", "/somewhere/else"])

# Start by calling the configure function
global_config.configure(
    # A root directory for the files RSS Glue will generate
    static_root="/etc/rssglue/static",
    # A root directory for the place Playwright (chrome) will keep its user directory
    playwright_root="/etc/rssglue/playwright",
    # The base public URL to use for building reference links
    base_url="http://localhost:5000/static/",
    # (Optional) a function to run when files change
    # run_after_generate=run_after_generate,
)

# All times and schedules are in UTC
cron_m_w_f = "0 5 * * 1,3,5"
cron_daily_6_am = "0 5 * * *"
cron_weekly_on_sunday = "0 5 * * 0"

# Finally, declare your artifacts
artifacts = [
    RssOutput(
        # A simple feed of NASA instagram posts
        InstagramFeed("nasa", schedule=cron_daily_6_am),
        # A weekly digest of the F1 subreddit
        DigestFeed(
            RssFeed(
                "r_formula1_top_week",
                "https://www.reddit.com/r/formula1/top.rss?t=week",
                limit=20,
                schedule=cron_weekly_on_sunday,
            )
        )
    )
]
```

## Design philosophy

RSS Glue is a simple python tool to manage feed generation and outputs exclusively to the local filesystem. The files it generates could be exposed with a web server, pushed up to an S3 bucket, or built into a netlify deployment. You don't need to operate a server or have some kind of docker host to run it.

It is not intended to scale beyond a few hundred feeds because, well, you're a human and you can't read all that anyway! It isn't intended to deploy as a multi-user app on the web. It will not get a frontend or a configuation language.

**Compared with RSSHub**

RSSHub is cool, but has several problems that RSS Glue tries to solve. The integrations I care about are either broken or don't work very well. Features like merge and digest are impossible under its stateless architecture.

You can use RSS Glue and RSSHub together though!

**Compared with Zapier**

Zapier suffers from trying to be all things to all people, and the configuration hell that such an endeavor always leads to.  It's kinda good at a lot of stuff.

