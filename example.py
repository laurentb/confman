#!/usr/bin/env python
from confman import ConfigSource

options = \
{
    'tags': ['desktop'],
    'hostname': 'test',
}

from sys import argv
from os import path
samples_path = path.join(path.dirname(argv[0]), 'samples')

c = ConfigSource(samples_path, "/tmp/dotfiles-test", None, options)
c.analyze()
c.check()
c.sync()

print
from pprint import pprint
pprint(c)
