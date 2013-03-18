#!/usr/bin/env python
import os
import sys
parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parentdir)

from confman import ConfigSource

options = {
    'tags': ['desktop'],
    'hostname': 'test',
}

samples_path = os.path.join(os.path.dirname(__file__), 'src')

c = ConfigSource(samples_path, "/tmp/dotfiles-test", None, options)
c.sync()

print
print repr(c)
