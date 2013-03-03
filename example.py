#!/usr/bin/env python
from confman import ConfigSource

options = {
    'tags': ['desktop'],
    'hostname': 'test',
}

from os import path
samples_path = path.join(path.dirname(__file__), 'samples')

c = ConfigSource(samples_path, "/tmp/dotfiles-test", None, options)
c.sync()

print
from pprint import pprint
pprint(c)
