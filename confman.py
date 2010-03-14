from __future__ import with_statement

import os
import re

class ConfigActionException(Exception):
    def __init__(self, action, value):
        self.action = action
        super(self.__class__, self).__init__(value)

    def __str__(self):
        return super(self.__class__, self).__str__() + " (" + repr(self.action) + ")"

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
        source = self.source_path()
        if not os.path.exists(source):
            raise ConfigActionException(self, "Source does not exists")

        dest = self.dest_path()
        if os.path.lexists(dest):
            if not os.path.islink(dest):
                raise ConfigActionException(self, "Destination exists and is not a link")

    def sync(self):
        source = self.source_path()
        dest = self.dest_path()
        if os.path.lexists(dest):
            # if the link already exists
            if os.path.islink(dest):
                # if the old link is broken or incorrect
                if not os.path.exists(dest) \
                or not os.path.samefile(dest, source):
                    os.unlink(dest)
                    print "Link target altered"
                else:
                    return
        else:
            self._makedirs()

        relsource = os.path.normpath(os.path.relpath(source, os.path.join(self.config.dest, self.relpath)))
        os.symlink(relsource, dest)
        print "Created new link: "+dest+" => "+source


class CopyConfigAction(ConfigAction):
    pass #TODO


class ProgrammableConfigAction(ConfigAction):
    matched = re.compile("\.p\.py$")

    @classmethod
    def matches(cls, filename):
        if cls.matched.search(filename):
            return cls.matched.sub("", filename)
        return False

    def check(self):
        class SymlinkForwarder(Exception):
            def __init__(self, filename):
                self.filename = filename

        class IgnoreForwarder(Exception):
            pass

        def redirect(filename):
            raise SymlinkForwarder("_"+filename)

        def ignore():
            raise IgnoreForwarder()

        exec_env = \
        {
            "options": self.config.options,
            "redirect": redirect,
            "ignore": ignore,
        }

        source = self.source_path()
        try:
            with open(source, "r") as file:
                exec compile(file.read(), source, 'exec') in exec_env
        except SymlinkForwarder as e:
            self.proxy = SymlinkConfigAction(self.config, self.relpath, e.filename, self.dest)
        except IgnoreForwarder as e:
            self.proxy = None
        else:
            raise ConfigActionException(self, "Unknown result")

        if not self.proxy is None:
            return self.proxy.check()

    def sync(self):
        if not self.proxy is None:
            return self.proxy.sync()

    def __repr__(self):
        return self.__class__.__name__+': '+self.source+' => PROXY '+repr(self.proxy)



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
    def __init__(self, source, dest, classes = None, options = None):
        # handle '~'
        self.source = os.path.expanduser(source)
        self.dest = os.path.expanduser(dest)

        if classes:
            self.classes = classes
        else:
            self.classes = [
                ProgrammableConfigAction,
                IgnoreConfigAction,
                SymlinkConfigAction,
            ]

        if options:
            self.options = options
        else:
            self.options = []

    def sync(self):
        "gather files and synchronize them"
        self.analyze()
        self.execute()

    def analyze(self):
        "gather all files"
        def walker(_, path, files):
            relpath = os.path.relpath(path, self.source)
            for filename in (file for file in files \
            if not os.path.isdir(os.path.join(path, file))):
                self.add(relpath, filename)

        self.tree = {}
        os.path.walk(self.source, walker, None)

    def add(self, relpath, filename):
        "add a file if it can be associated to an action"
        def get_file_class(filename):
            for cls in self.classes:
                dest = cls.matches(filename)
                if dest is not False:
                    return (cls, dest)
            raise Exception("No class found for "+os.path.join(relpath, filename))

        cls, dest = get_file_class(filename)

        if dest is not None:
            files = self.tree.setdefault(relpath, {})
            if files.has_key(dest):
                raise Exception('Conflict: '+filename+' with '+files[dest])
            files[dest] = cls(self, relpath, filename, dest)

    def execute(self):
        "executes all actions if everything is alright"
        for file in self:
            file.check()
        for file in self:
            file.sync()

    def __iter__(self):
        "iterate over all analyzed files"
        for files in self.tree.itervalues():
            for file in files.itervalues():
                yield file

    def __repr__(self):
        return "\n".join(\
            (action.relpath+': '+repr(action) for action in self))

