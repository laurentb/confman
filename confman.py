from __future__ import with_statement

import os
import re
import os.path as osp

# Python <2.6 compatibility
try:
    from os.path import relpath as osp_relpath
except ImportError:
    def osp_relpath(path, start=osp.curdir):
        """Return a relative version of a path"""

        if not path:
            raise ValueError("no path specified")

        start_list = osp.abspath(start).split(osp.sep)
        path_list = osp.abspath(path).split(osp.sep)

        # Work out how much of the filepath is shared by start and path.
        i = len(osp.commonprefix([start_list, path_list]))

        rel_list = [osp.pardir] * (len(start_list)-i) + path_list[i:]
        if not rel_list:
            return osp.curdir
        return osp.join(*rel_list)


class ActionException(Exception):
    def __init__(self, action, value):
        self.action = action
        super(self.__class__, self).__init__(value)

    def __str__(self):
        return super(self.__class__, self).__str__() + " (" + repr(self.action) + ")"


class Action(object):
    @classmethod
    def matches(cls, filename):
        """
        Tells if the file should be associated with this action.
        Returns False if not; confman will try with the next class.
        Returns None if the file should be ignored.
        Returns the destination filename (str) if it matches.
        """
        raise NotImplementedError()

    def __init__(self, config, relpath, source, dest):
        self.source = source
        self.dest = dest
        self.relpath = relpath
        self.config = config

    def __repr__(self):
        return self.__class__.__name__+": "+self.relpath+"/"+self.source+" => "+self.dest

    def check(self):
        raise NotImplementedError()

    def sync(self):
        raise NotImplementedError()

    def dest_path(self):
        return osp.normpath(\
            osp.join(self.config.dest, self.relpath, self.dest))

    def source_path(self):
        return osp.normpath(\
            osp.join(self.config.source, self.relpath, self.source))

    def _makedirs(self):
        dir = osp.dirname(self.dest_path())
        if not osp.isdir(dir):
            os.makedirs(dir)


class SymlinkAction(Action):
    @classmethod
    def matches(cls, filename):
        return filename

    def check(self):
        source = self.source_path()
        if not osp.exists(source):
            raise ActionException(self, "Source does not exists")

        dest = self.dest_path()
        if osp.lexists(dest):
            if not osp.islink(dest):
                raise ActionException(self, "Destination exists and is not a link")

    def sync(self):
        source = self.source_path()
        dest = self.dest_path()
        if osp.lexists(dest):
            # if the link already exists
            if osp.islink(dest):
                # if the old link is broken or incorrect
                if not osp.exists(dest) \
                or not osp.samefile(dest, source):
                    os.unlink(dest)
                    print "Link target altered"
                else:
                    return
        else:
            self._makedirs()

        relsource = osp.normpath(osp_relpath(source, osp.join(self.config.dest, self.relpath)))
        os.symlink(relsource, dest)
        print "Created new link: "+dest+" => "+source


class EmptyAction(Action):
    """
    Ensures the destination file exists.
    Creates an empty one if not.
    """
    matched = re.compile("\.empty$")

    @classmethod
    def matches(cls, filename):
        if cls.matched.search(filename):
            return cls.matched.sub("", filename)
        return False

    def check(self):
        pass

    def sync(self):
        dest = self.dest_path()
        # if the file does not exist
        if not osp.exists(dest):
            # but it's a broken link
            if osp.islink(dest):
                raise ActionException(self, "Destination is a broken link")
            else:
                self._makedirs()
                open(dest, "w").close()
                print "Created new empty file: "+dest

    def __repr__(self):
        return self.__class__.__name__+": EMPTY => "+self.dest


class CopyAction(Action):
    pass #TODO


class Forwarder(Exception):
    def get_proxy(self, parent):
        raise NotImplementedError()


class SymlinkForwarder(Forwarder):
    def __init__(self, filename):
        self.filename = filename

    def get_proxy(self, parent):
        return SymlinkAction(parent.config, parent.relpath, self.filename, parent.dest)


class EmptyForwarder(Forwarder):
    def get_proxy(self, parent):
        return EmptyAction(parent.config, parent.relpath, None, parent.dest)


class IgnoreForwarder(Forwarder):
    def get_proxy(self, parent):
        return None


class ProgrammableAction(Action):
    matched = re.compile("\.p\.py$")

    @classmethod
    def matches(cls, filename):
        if cls.matched.search(filename):
            return cls.matched.sub("", filename)
        return False

    def get_env(self):
        """
        Get limited environment execution.
        This function could be overloaded to add some custom methods.
        """
        def redirect(filename):
            raise SymlinkForwarder("_"+filename)

        def empty():
            raise EmptyForwarder()

        def ignore():
            raise IgnoreForwarder()

        exec_env = \
        {
            "options": self.config.options,
            "redirect": redirect,
            "empty": empty,
            "ignore": ignore,
        }

        return exec_env

    def check(self):
        source = self.source_path()
        try:
            with open(source, "r") as file:
                exec_env = self.get_env()
                exec compile(file.read(), source, "exec") in exec_env
        except Forwarder, e:
            self.proxy = e.get_proxy(self)
        else:
            raise ActionException(self, "Unknown result")

        if not self.proxy is None:
            return self.proxy.check()

    def sync(self):
        if not self.proxy is None:
            return self.proxy.sync()

    def __repr__(self):
        return self.__class__.__name__+": "+self.source+" => PROXY "+repr(self.proxy)


class IgnoreAction(Action):
    ignored = re.compile("_|\.git$|\.gitignore$")

    @classmethod
    def matches(cls, filename):
        if cls.ignored.match(filename):
            return None
        return False

    def __repr__(self):
        return self.__class__.__name__+": "+self.source+" => IGNORED"


class ConfigSource(object):
    def __init__(self, source, dest, classes = None, options = None):
        # handle '~'
        self.source = osp.expanduser(source)
        self.dest = osp.expanduser(dest)

        if classes:
            self.classes = classes
        else:
            self.classes = [
                ProgrammableAction,
                IgnoreAction,
                EmptyAction,
                SymlinkAction,
            ]

        if options:
            self.options = options
        else:
            self.options = []

    def sync(self):
        "Gather files and synchronize them."
        self.analyze()
        self.execute()

    def analyze(self):
        "Gather all files."
        def walker(_, path, files):
            relpath = osp_relpath(path, self.source)
            for filename in (file for file in files \
            if not osp.isdir(osp.join(path, file))):
                self.add(relpath, filename)

        self.tree = {}
        osp.walk(self.source, walker, None)

    def _get_file_class(self, filename):
        """
        Returns the first class that accepts (matches) the file.
        It will fail if no class accepts or tells to ignore.
        """
        for cls in self.classes:
            dest = cls.matches(filename)
            if dest is not False:
                return (cls, dest)
        raise Exception("No class found for "+filename)

    def add(self, relpath, filename):
        """
        Add a file if it can be associated to an action.
        filename is the destination filename; it will check for conflicts
        """
        cls, dest = self._get_file_class(filename)

        if dest is not None:
            files = self.tree.setdefault(relpath, {})
            if files.has_key(dest):
                raise Exception("Conflict: "+filename+" with "+files[dest])
            files[dest] = cls(self, relpath, filename, dest)

    def execute(self):
        "Executes all actions if everything is alright."
        for file in self:
            file.check()
        for file in self:
            file.sync()

    def __iter__(self):
        "Iterates over all analyzed files."
        for files in self.tree.itervalues():
            for file in files.itervalues():
                yield file

    def __repr__(self):
        return "\n".join(\
            (action.relpath+": "+repr(action) for action in self))

