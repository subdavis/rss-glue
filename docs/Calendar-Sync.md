I want to build an automation that reads posts from an RSS feed, determines if they are posts about an event that someone might attend, and puts them into a google calendar.

It's likely that the same event may appear in the feed multiple times.  The RSS posts are largely going to be derived from instagram posts using a merge feed from RSS glue (this app) but I want to keep this automation completely separate from RSS Glue.

My idea is to build this using Claude Code because I suspect it's going to involve intelligent manipulation of the calendar (For example, an event may be announced, announced again, postponed, and then canceled).

I want to be able to run a command that processes new posts from the feed one at a time and only processes them once.

Event information may be embedded in the image only (it could be a poster) so I want to feed the images in as well.

I'm evaluating an MCP that has these tools.

```
list-calendars	List all available calendars
list-events	List events with date filtering
get-event	Get details of a specific event by ID
search-events	Search events by text query
create-event	Create new calendar events
update-event	Update existing events
delete-event	Delete events
respond-to-event	Respond to event invitations (Accept, Decline, Maybe, No Response)
get-freebusy	Check availability across calendars, including external calendars
get-current-time	Get current date and time in calendar's timezone
list-colors	List available event colors
manage-accounts	Add, list, or remove connected Google accounts
```

## Idea 1: Claude Skill

I think this might even been something where a sophisticated Claude Skill + some custom code and access to Google Calendar via an MCP server would be most versatile.

## Idea 2: Command line tool that invokes Claude Code SDK

It might be better to have a deterministic program pull the latests posts and invoke claude code sdk once per post.

## Sample data

https://rssglue.subdavis.com/feed/ig-bonesawcyclingcollective/rss