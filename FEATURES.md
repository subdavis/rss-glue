I would like to build an RSS tool that can:

* Create RSS sources from various inputs
* Merge feeds
* Create Digests based on a cron schedule.

I have a version 1 implementation that I am not happy with.

* I chose a CLI-based, static generation approach using the filesystem as a database.
* I chose a complicated inheritence pattern to write new feeds that is difficult to reason about and debug.
* I chose to make cache its own feed type.  I'd like for cacheing to be an optional feature of every feed

That implementation is in ../rss-glue

I would like to build  a version 2 with a different tech stack and simpler architecture.

uv, FastAPI, SQLModel.

I'm imagining:

* a feed table
* a many-to-many relation for feed relationships
* a post table
* update history

I believe we will still need to do a reverse-topo-sort for update order.

I would like the outputs to be server-rendered rather than static generated.

In the first pass, let's focus on the core functionality:

- A basic RSS source
- A way to merge feeds
- An RSS output endpoint


Instead of configuration with a python input file, I'd like a JSON config.  


For the frontend, I want simple jinja pages with NO CSS. I would like to begin with 1 page to list the configured feeds and link to their outputs, and a page with a textarea to input the configuration JSON.  

Come up with something reasonable for the config syntax, write a pydantic validator for it, and document it well.


The new project should  be called rssglue

Please implement these follow-up features:

## Feature: HTML Preview

Please build an HTML preview of the RSS Feed.

## Feature: Media Cache

When a feed UPDATES and has media embedded OR attached, that media should be downloaded. The media should be stored on disk and referenced in the DB in a reasonable way.  

This is a feature that should exist for every feed type, and be configurable per-feed.  There should also be a global cache enablement option so each feed can override the global if necessary.

## Feature: Implement other sources

instagram, facebook, hackernews JSON

## Feature: Digest

Implement the digest feature similar to v1 with a cron schedule.