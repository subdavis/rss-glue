from rss_glue.feeds import RedditFeed
from rss_glue.resources import global_config

global_config.configure()

sources = [RedditFeed("https://www.reddit.com/r/selfhosted.json")]
