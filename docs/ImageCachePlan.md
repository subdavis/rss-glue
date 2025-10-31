## Image cache feature

Sometimes feeds contain images in their html content, i.e. `<img src="...">`

Often, these images come with unfriendly CORS policies that prevent them from being rendered in a browser. They are also occasionally unstable links that expire after a long enough time.

Let's build an image caching feature into this tool.

I think it would be a good idea to make this optional and composable, so let's make a `CacheFeed` that can take in a source and mostly pass through its functionality except for the part where it replaces the remote references to images with a local reference.

You can base a bit of this off of the digest and merge feeds, which are also "meta" feeds in that they take in another feed as a source.

Use the FileCache from global config as the file store.  Remember that rendering the post contents should render the source contents but replace the media with a relative path to the local cache.  I believe the caches and config have the necessary variables to get the base path correct.