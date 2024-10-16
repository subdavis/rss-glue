import random

human_strftime = "%a, %b %d %I:%M %p"


def rand_range(base: int, top: int):
    return base + (random.random() * top)
