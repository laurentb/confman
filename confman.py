from __future__ import absolute_import, print_function

import os
import os.path as osp
import re
from string import Template


class ConfmanException(Exception):
    pass


class ActionException(ConfmanException):
    def __init__(self, action, value, resolve=None):
        self.action = action
        self.resolve = resolve
        ConfmanException.__init__(self, value)

    def __str__(self):
        s = "%s (%s)" % (ConfmanException.__str__(self), repr(self.action))
        if self.resolve:
            s += "\nResolve the issue with:\n%s" % self.resolve
        return s


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
        self.config = config
        self.relpath = relpath
        self.source = source
        self.dest = dest

    def __repr__(self):
        return "%s: %s => %s" % (self.__class__.__name__,
                                 osp.join(self.relpath, self.source),
                                 self.dest)

    def check(self):
        raise NotImplementedError()

    def sync(self):
        raise NotImplementedError()

    def dest_path(self):
        return osp.normpath(
            osp.join(self.config.dest, self.relpath, self.dest))

    def source_path(self):
        return osp.normpath(
            osp.join(self.config.source, self.relpath, self.source))

    def _makedirs(self):
        dir = osp.dirname(self.dest_path())
        if not osp.isdir(dir):
            os.makedirs(dir)


class SymlinkAction(Action):
    FORCE_SAME = True
    "Force replace destination file by symlink if source has same contents"

    @classmethod
    def matches(cls, filename):
        return filename

    def same_contents(self):
        source = self.source_path()
        dest = self.dest_path()
        with open(source) as s, open(dest) as d:
            return s.read() == d.read()

    def check(self):
        source = self.source_path()
        if not osp.exists(source):
            raise ActionException(self, "Source does not exists")

        dest = self.dest_path()
        if osp.lexists(dest):
            if not osp.islink(dest) and not (self.FORCE_SAME and self.same_contents()):
                resolve = "diff %s %s\nrm -vi %s" % (osp.abspath(source), osp.abspath(dest), osp.abspath(dest))
                raise ActionException(self,
                                      "Destination exists and is not a link",
                                      resolve=resolve)

    def sync(self):
        source = self.source_path()
        dest = self.dest_path()
        if osp.lexists(dest):
            # if the link already exists
            if osp.islink(dest):
                # if the old link is broken or incorrect
                if not osp.exists(dest) or not osp.samefile(dest, source):
                    os.unlink(dest)
                    print("Link target altered")
                else:
                    return
            # if the destination is not a link, but has same contents as source
            elif self.FORCE_SAME and self.same_contents():
                os.unlink(dest)
                print("Link target was a file with same contents")
        else:
            self._makedirs()

        relsource = osp.normpath(osp.relpath(source,
                                             osp.join(self.config.dest, self.relpath)))
        os.symlink(relsource, dest)
        print("Created new link: %s => %s" % (dest, source))


class TextAction(Action):
    ONCE = False

    def check(self):
        """
        This action can't be invoked by a file;
        the source parameter is used to provide the text.
        It is used by a ProgrammableAction.
        """
        if self.source is not None:
            self.text = self.source
            self.source = None

    def sync(self):
        """
        Write the file only if necessary
        """
        dest = self.dest_path()
        exists = osp.exists(dest)
        if osp.islink(dest):
            raise ActionException(self, "Destination is a link")
        else:
            self._makedirs()
            with open(dest, 'a+') as destfile:
                destfile.seek(0)
                if destfile.read() != self.text:
                    if exists and self.ONCE:
                        print("File already exists, not updated: %s" % dest)
                    else:
                        print("Updated file contents: %s" % dest)
                        destfile.truncate(0)
                        destfile.write(self.text)

    def __repr__(self):
        return "%s: TEXT => %s" % (self.__class__.__name__, self.dest)


class CopyAction(TextAction):
    MATCHED = re.compile(r'\.copy$')

    @classmethod
    def matches(cls, filename):
        if cls.MATCHED.search(filename):
            return cls.MATCHED.sub('', filename)
        return False

    def check(self):
        """
        Retrieve the text from the source file.
        """
        source = self.source_path()
        with open(source, "r") as sourcefile:
            self.text = sourcefile.read()


class CopyOnceAction(CopyAction):
    ONCE = True
    MATCHED = re.compile(r'\.copyonce$')

    @classmethod
    def matches(cls, filename):
        if cls.MATCHED.search(filename):
            return cls.MATCHED.sub('', filename)
        return False


class EmptyAction(CopyOnceAction):
    """
    Ensures the destination file exists.
    Creates an empty one if not.
    """
    MATCHED = re.compile(r'\.empty$')

    @classmethod
    def matches(cls, filename):
        if cls.MATCHED.search(filename):
            return cls.MATCHED.sub('', filename)
        return False

    def check(self):
        self.text = ''

    def __repr__(self):
        return "%s: EMPTY => %s" % (self.__class__.__name__, self.dest)


class Forwarder(ConfmanException):
    """
    Not really an error, it is used to go back to confman with a value
    when executing a ProgrammableAction.
    """
    def get_proxy(self, parent):
        raise NotImplementedError()


class SymlinkForwarder(Forwarder):
    def __init__(self, filename):
        self.filename = filename

    def get_proxy(self, parent):
        return SymlinkAction(parent.config, parent.relpath,
                             self.filename, parent.dest)


class EmptyForwarder(Forwarder):
    def get_proxy(self, parent):
        return EmptyAction(parent.config, parent.relpath,
                           None, parent.dest)


class TextForwarder(Forwarder):
    def __init__(self, text):
        self.text = text

    def get_proxy(self, parent):
        # The text is passed as source
        return TextAction(parent.config, parent.relpath,
                          self.text, parent.dest)


class IgnoreForwarder(Forwarder):
    def get_proxy(self, parent):
        return None


class ProgrammableAction(Action):
    MATCHED = re.compile(r'\.p\.py$')

    @classmethod
    def matches(cls, filename):
        if cls.MATCHED.search(filename):
            return cls.MATCHED.sub('', filename)
        return False

    def get_env(self):
        """
        Get limited environment execution.
        This function could be overloaded to add some custom methods.
        """
        options = self.config.options  # NOQA

        def redirect(filename):
            raise SymlinkForwarder('_%s' % filename)

        def empty():
            raise EmptyForwarder()

        def ignore():
            raise IgnoreForwarder()

        class ConfmanTemplate(Template):
            def render(self, _strict=True, _warning=True, **kwargs):
                if _warning and 'warning' not in kwargs:
                    kwargs['warning'] = "WARNING: Do not edit this file, edit the template instead."
                if _strict:
                    raise TextForwarder(self.substitute(kwargs))
                raise TextForwarder(self.safe_substitute(kwargs))

        def template(name):
            source = osp.join(osp.dirname(self.source_path()), "_%s" % name)
            with open(source) as handle:
                text = handle.read()
            return ConfmanTemplate(text)

        def text(text):
            return ConfmanTemplate(text)

        return locals()

    def check(self):
        source = self.source_path()
        try:
            with open(source, 'r') as file:
                exec_env = self.get_env()
                exec(compile(file.read(), source, 'exec'), exec_env)
        except Forwarder as e:
            self.proxy = e.get_proxy(self)
        else:
            raise ActionException(self, "Unknown result")

        if self.proxy is not None:
            return self.proxy.check()

    def sync(self):
        if self.proxy is not None:
            return self.proxy.sync()

    def __repr__(self):
        return "%s: %s => PROXY %s" % (self.__class__.__name__,
                                       self.source, repr(self.proxy))


class IgnoreAction(Action):
    IGNORED = re.compile(r'_|\.git$|\.gitignore$')

    @classmethod
    def matches(cls, filename):
        if cls.IGNORED.match(filename):
            return None
        return False

    def __repr__(self):
        return "%s: %s => IGNORED" % (self.__class__.__name__, self.source)


class ConfigSource(object):
    DEFAULT_CLASSES = (
        ProgrammableAction,
        IgnoreAction,
        EmptyAction,
        CopyAction,
        CopyOnceAction,
        SymlinkAction,
    )
    ACT_AS_FILE = re.compile(r'\.F$')

    def __init__(self, source, dest, classes=None, options=None):
        # handle '~'
        self.source = osp.expanduser(source)
        self.dest = osp.expanduser(dest)

        self.classes = classes or self.DEFAULT_CLASSES
        self.options = options

    def sync(self):
        """
        Gather files and synchronize them.
        """
        print("Synchronizing files from %s to %s..." % (self.source, self.dest))
        self.analyze()
        self.execute()

    def analyze(self):
        """
        Gather all files.
        """
        self.tree = {}
        for path, dirs, files in os.walk(self.source, topdown=True):
            relpath = osp.relpath(path, self.source)

            to_remove = []
            for filename in dirs:
                if self.ACT_AS_FILE.search(filename):
                    to_remove.append(filename)
                    self.add_dir(relpath, filename)
            for filename in to_remove:
                # this list can be modified in place
                # but we wust not remove elements when iterating on it!
                dirs.remove(filename)

            for filename in files:
                self.add(relpath, filename)

    def _get_file_class(self, filename):
        """
        Returns the first class that accepts (matches) the file.
        It will fail if no class accepts or tells to ignore.
        """
        for cls in self.classes:
            dest = cls.matches(filename)
            if dest is not False:
                return (cls, dest)
        raise ConfmanException("No class found for %s" % filename)

    def add(self, relpath, filename):
        """
        Add a file if it can be associated to an action.
        filename is the source filename.
        The destination will be deduced, and it will check for conflicts.
        """
        cls, dest = self._get_file_class(filename)
        if dest is not None:
            return self._add(relpath, filename, cls, dest)

    def add_dir(self, relpath, filename):
        """
        Add a directory as if it was a file.
        It will try to associate it with a particular file class,
        though it does not make much sense in most cases.
        filename is the source filename.
        The destination will be deduced, and it will check for conflicts.
        """
        cls, dest = self._get_file_class(filename)
        if dest is not None:
            dest = self.ACT_AS_FILE.sub("", dest)
            return self._add(relpath, filename, cls, dest)

    def _add(self, relpath, filename, cls, dest):
        files = self.tree.setdefault(relpath, {})
        if dest in files:
            raise ConfmanException("Conflict: %s with %s" % (filename, files[dest]))
        files[dest] = cls(self, relpath, filename, dest)

    def execute(self):
        """
        Executes all actions if everything is alright.
        """
        for f in self:
            f.check()
        for f in self:
            f.sync()

    def __iter__(self):
        """
        Iterates over all analyzed files.
        """
        for files in self.tree.values():
            for f in files.values():
                yield f

    def __repr__(self):
        return "\n".join(
            ("%s: %s" % (action.relpath, repr(action)) for action in self))
