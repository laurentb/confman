#!/usr/bin/env python

from confman import ConfigSource

c = ConfigSource("~/dotfiles", "/tmp/dotfiles-test")
c.analyze()
c.check()
c.sync()

from pprint import pprint
pprint(c)
