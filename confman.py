import os
import re

class ConfigAction(object):
    @classmethod
    def matches(cls, filename):
        raise Exception('Not implemented')

    def __init__(self, config, relpath, source, dest):
        self.source = source
        self.dest = dest
        self.relpath = relpath
        self.config = config

    def __repr__(self):
        return self.__class__.__name__+': '+self.source+' => '+self.dest

    def check(self):
        raise Exception('Not implemented')

    def sync(self):
        raise Exception('Not implemented')

    def dest_path(self):
        return os.path.normpath(\
            os.path.join(self.config.dest, self.relpath, self.dest))

    def source_path(self):
        return os.path.normpath(\
            os.path.join(self.config.source, self.relpath, self.source))

    def _makedirs(self):
        dir = os.path.dirname(self.dest_path())
        if not os.path.isdir(dir):
            os.makedirs(dir)


class SymlinkConfigAction(ConfigAction):
    @classmethod
    def matches(cls, filename):
        return filename

    def check(self):
        dest = self.dest_path()
        if os.path.lexists(dest):
            if not os.path.islink(dest):
                raise Exception("Destination exists and is not a link")

    def sync(self):
        source = self.source_path()
        dest = self.dest_path()
        if os.path.lexists(dest):
            if os.path.islink(dest):
                if not os.path.samefile(dest, source):
                    os.unlink(dest)
                    print "Link target altered"
                else:
                    return
        else:
            self._makedirs()

        print "Created new link: "+dest+" => "+source
        os.symlink(source, dest)

class CopyConfigAction(ConfigAction):
    pass #TODO


class IgnoreConfigAction(ConfigAction):
    ignored = re.compile("_|\.git$|\.gitignore$")

    @classmethod
    def matches(cls, filename):
        if cls.ignored.match(filename):
            return None
        return False

    def __repr__(self):
        return self.__class__.__name__+': '+self.source+' => IGNORED'


class ConfigSource(object):
    def __init__(self, source, dest, classes = None):
        # handle '~'
        self.source = os.path.expanduser(source)
        self.dest = os.path.expanduser(dest)

        if classes:
            self.classes = classes
        else:
            self.classes = [
                IgnoreConfigAction,
                SymlinkConfigAction,
            ]

    def analyze(self):
        def walker(_, path, files):
            relpath = os.path.relpath(path, self.source)
            for filename in (file for file in files \
            if not os.path.isdir(os.path.join(path, file))):
                self.add(relpath, filename)

        self.tree = {}
        os.path.walk(self.source, walker, None)

    def add(self, relpath, filename):
        def get_file_class(filename):
            for cls in self.classes:
                dest = cls.matches(filename)
                if dest is not False:
                    return (cls, dest)
            raise Exception("No class found")

        cls, dest = get_file_class(filename)

        if dest is not None:
            files = self.tree.setdefault(relpath, {})
            if files.has_key(dest):
                raise Exception('Conflict: '+filename+' with '+files[dest])
            files[dest] = cls(self, relpath, filename, dest)

    def check(self):
        for file in self:
            file.check()

    def sync(self):
        for file in self:
            file.sync()

    def __iter__(self):
        for files in self.tree.itervalues():
            for file in files.itervalues():
                yield file

    def __repr__(self):
        return "\n".join(\
            (action.relpath+': '+repr(action) for action in self))

