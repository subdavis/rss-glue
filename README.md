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
* `RedditFeed` because the standard Reddit RSS feed leaves out too much content and you can get more from the JSON api.

Meta Data Sources

* `MergeFeed` is a simple chronological merge of multiple feeds.
* `DigestFeed` is a periodical rollup of a feed, such as a daily digest.
* `AiFilterFeed` is a feed filtered by a prompt to some AI backend.

Outputs

* `RssOutput` is an output RSS feed.
* `HTMLOutput` is a very basic single page web feed output.
* `HTMLIndexOutput` is a meta-output HTML page with a link to all its child outputs. Handy for quick reference and adding feeds to your RSS reader.
* `OpmlOutput` is a meta-output OPML file with links to all the RSS outputs for quick import into RSS readers.

## Quick Start

### Local Install (pip)

```bash
# Install RSS Glue
pip install rss-glue

# Create your configuration file and edit it
touch config.py

# Then generate your feed
rss-glue --config config.py update
# Or start a long-running process
rss-glue --config config.py watch
# Or start the debug web server
rss-glue --config config.py debug
```

### Docker

RssGlue can be run with docker, and requires that its static files be served with a regular web server such as nginx or caddy.

```bash
# You can build the container yourself
docker buildx build -t rssglue .
```

There's a sample docker-compose to do this in [./docker-compose.yml](./docker-compose.yml).

```bash
docker compose up -d
```

### Deploying with GitHub Pages

Because this is more like a static site generator than a web service, you can deploy it without any of your own infrastructure using a continuous integration job that runs on a timer and push the files to any static server like S3, Google Cloud Buckets, Netlify, or GH Pages.

## Configuration

RSS Glue is configured entirely with Python. Here's an example.

```python
from rss_glue.feeds import DigestFeed, MergeFeed, RssFeed
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
    # The base public URL to use for building reference links
    base_url="http://localhost:5000/static/",
    # (Optional) a function to run when files change
    # run_after_generate=run_after_generate,
)

# All times and schedules are in UTC
cron_weekly_on_sunday = "0 5 * * 0"

_outputs = [
    # A weekly digest of the F1 subreddit
    DigestFeed(
        RssFeed(
            "r_formula1_top_week", # A unique name for this feed.
            "https://www.reddit.com/r/formula1/top.rss?t=week",
            limit=20,
        )
        schedule=cron_weekly_on_sunday,
    )
]

# Finally, declare your artifacts
artifacts = [
    HTMLIndexOutput(
        OpmlOutput(RssOutput(*_outputs)),
        HTMLOutput(*_outputs),
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
