#!/usr/bin/env python

from confman import ConfigSource

options = \
{
    'tags': ['desktop'],
    'hostname': 'test',
}

c = ConfigSource("~/dotfiles", "/tmp/dotfiles-test", None, options)
c.analyze()
c.check()
c.sync()

print
from pprint import pprint
pprint(c)
