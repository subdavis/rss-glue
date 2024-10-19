import random

human_strftime = "%a, %b %d %I:%M %p"

# CSS should be a 500 pixel wide central column
page_css = """
body {
    font-family: Arial, sans-serif;
    margin: auto;
    width: 600px;
    max-width: 100%;
    background-color: #f0f0f0;
}
main {
    padding: 2em;
}
"""


def rand_range(low: int, high: int):
    return low + (random.random() * (high - low))
