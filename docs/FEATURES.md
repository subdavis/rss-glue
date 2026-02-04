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

## Feature: Background upgrade worker

Implement a background worker.

* It should sleep until the next scheduled update.
* next_update should be calculated per-feed and be part of the feed protocol.

Some special considerations:

1. Calculate the next update time per-feed
1. Sleep until the closest next update time
1. Wake up
1. If the feed you're going to update has dependencies, update them first.
1. Update the feed.
1. Start over, and sleep to the next closest update time.

* I want this process to be able to run in the background and started by the normal fastapi app.
* I want to be able to run the web server without this background process in development mode if I choose by setting an environment variable.

## Authentication

Needs username and password auth.

Anonymous users should not have access to the configuraiton page or the ability to trigger mutations like update and reset.

Otherwise, anon users can access feeds, gallery, and everything else.

If the users table is empty, special case where the user is prompted to make an account on first login.  

Hash and salt the password in the standard way.

## Broken stuff

Cron expressions need to be evaluated in local time rather than UTC.