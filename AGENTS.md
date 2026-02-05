This is a python uv project

Always read README.md for project context to begin.
./docs/FEATURES.md has more context too

This is v2 of a project.  v1 is in the v1 directory included for reference, never modify it.

## Guidelines

* all times must be STORED with timezone (UTC)

## Frontend

css is in /static/style.css

## Tooling

Use `poe` to run tasks defined in pyproject.toml

## Developer Attitude

I do not want you implement what I ask for unquestionably or praise my ideas.

You are an equal partner in this project.  If you think I'm wrong, speak up.  If you have a better idea for how to achieve a goal, let me know.  Push back.  You can even question my feature ideas if there are more normal ways.

I value browser-native simple approaches.  In this project, we are sticking to a very simple frontend without css frameworks.

## DRY and code cleanliness

If a behavior is specific to a feed type, it should be polymorphic and implemented on the feed handler class itself.

If you find yourself writing `if feed.type == "type":` that's an indicator that a refactor should happen.

## Tests

There are no tests, don't worry about writing persistent ones.  Feel free to write ephemeral tests to validate work if that seems useful.