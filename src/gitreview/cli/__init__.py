#!/usr/bin/python -tt
#
# Copyright 2009-2010 Facebook, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#
from __future__ import absolute_import, division, print_function

import readline
import sys
import traceback

import pycompat
from .exceptions import *
from . import tokenize

# Import everything from our command and args submodules
# into the top-level namespace
from .command import *
from .args import *


class CLI(object):
    """
    Class for implementing command line interfaces.

    (We define our own rather than using the standard Python cmd module,
    since cmd.Cmd doesn't provide all the features we want.)
    """
    def __init__(self):
        # Configuration, modifiable by subclasses
        self.completekey = 'tab'
        self.prompt = '> '

        # Normally, empty lines and EOF won't be stored in self.prev_line
        # (the contents of self.prev_line remain be unchanged when one of these
        # is input).  self.remember_empty_line can be set to True to override
        # this behavior.
        #
        # Setting this to True will
        # implementation of self.emptyline
        # If self.remember_empty_line is True,
        # self.prev_line will be updated
        self.remember_empty_line = False

        # State, modifiable by subclasses
        self.stop = False
        self.line = None
        self.cmd = None
        self.args = None
        self.prev_line = None
        self.commands = {}

        # Private state
        self._old_completer = None

    def add_command(self, name, command):
        if name in self.commands:
            raise KeyError('command %r already exists' % (name,))
        self.commands[name] = command

    def get_command(self, name):
        """
        cli.get_command(name) --> entry

        Get a command entry, based on the command name, or an unambiguous
        prefix of the command name.

        Raises NoSuchCommandError if there is no command matching this name
        or starting with this prefix.  Raises AmbiguousCommandError if the
        name does not exactly match a command name, and there are multiple
        commands that start with this prefix.
        """
        # First see if we have an exact match for this command
        try:
            return self.commands[name]
        except KeyError:
            # Fall through
            pass

        # Perform completion to see how many commands match this prefix
        matches = self.complete_command(name)
        if not matches:
            raise NoSuchCommandError(name)
        if len(matches) > 1:
            raise AmbiguousCommandError(name, matches)
        return self.commands[matches[0]]

    def output(self, msg='', newline=True):
        # XXX: We always write to sys.stdout for now.
        # This isn't configurable, since they python readline module
        # always uses sys.stdin and sys.stdout
        sys.stdout.write(msg)
        if newline:
            sys.stdout.write('\n')

    def output_error(self, msg):
        sys.stderr.write('error: %s\n' % (msg,))

    def readline(self):
        try:
            return pycompat.readline(self.prompt)
        except EOFError:
            return None

    def loop(self):
        # Always reset self.stop to False
        self.stop = False

        rc = None
        self.setup_readline()
        try:
            while not self.stop:
                try:
                    line = self.readline()
                    rc = self.run_command(line)
                except KeyboardInterrupt:
                    # Don't exit on Ctrl-C, just abort the current command
                    # Print a newline, so that the next prompt will always
                    # start on its own line.
                    self.output(newline=True)
                    continue
        finally:
            self.cleanup_readline()

        return rc

    def loop_once(self):
        # Note: loop_once ignores self.stop
        # It doesn't reset it if it is True

        rc = None
        self.setup_readline()
        try:
            line = self.readline()
            rc = self.run_command(line)
        finally:
            self.cleanup_readline()

        return rc

    def run_command(self, line, store=True):
        if line == None:
            return self.handle_eof()

        if not line:
            return self.handle_empty_line()

        (cmd_name, args) = self.parse_line(line)
        rc = self.invoke_command(cmd_name, args, line)

        # If store is true, store the line as self.prev_line
        # However, don't remember EOF or empty lines, unless
        # self.remember_empty_line is set.
        if store and (line or self.remember_empty_line):
            self.prev_line = line

        return rc

    def invoke_command(self, cmd_name, args, line):
        try:
            cmd_entry = self.get_command(cmd_name)
        except NoSuchCommandError as ex:
            return self.handle_unknown_command(cmd_name)
        except AmbiguousCommandError as ex:
            return self.handle_ambiguous_command(cmd_name, ex.matches)

        try:
            return cmd_entry.run(self, cmd_name, args, line)
        except:
            return self.handle_command_exception()

    def handle_eof(self):
        self.output()
        self.stop = True
        return 0

    def handle_empty_line(self):
        # By default, re-execute the last command.
        #
        # This would behave oddly when self.remember_empty_line is True,
        # though, so do nothing if remember_empty_line is set.  (With
        # remember_empty_line on, the first time an empty line is entered would
        # re-execute the previous commands.  Subsequent empty lines would do
        # nothing, though.)
        if self.remember_empty_line:
            return 0

        # If prev_line is None (either no command has been run yet, or the
        # prevous command was EOF), or if it is empty, do nothing.
        if not self.prev_line:
            return 0

        # Re-execute self.prev_line
        return self.run_command(self.prev_line)

    def handle_unknown_command(self, cmd):
        self.output_error('%s: no such command' % (cmd,))
        return -1

    def handle_ambiguous_command(self, cmd, matches):
        self.output_error('%s: ambiguous command: %s' % (cmd, matches))
        return -1

    def handle_command_exception(self):
        ex = sys.exc_info()[1]
        if isinstance(ex, CommandArgumentsError):
            # CommandArgumentsError indicates the user entered
            # invalid arguments.  Just print a normal error message,
            # with no traceback.
            self.output_error(ex)
            return -1

        tb = traceback.format_exc()
        self.output_error(tb)
        return -2

    def complete(self, text, state):
        if state == 0:
            try:
                self.completions = self.get_completions(text)
            except:
                self.output_error('error getting completions')
                tb = traceback.format_exc()
                self.output_error(tb)
                return None

        try:
            return self.completions[state]
        except IndexError:
            return None

    def get_completions(self, text):
        # strip the string down to just the part before endidx
        # Things after endidx never affect our completion behavior
        line = readline.get_line_buffer()
        begidx = readline.get_begidx()
        endidx = readline.get_endidx()
        line = line[:endidx]

        (cmd_name, args, part) = self.parse_partial_line(line)
        if part == None:
            part = ''

        if cmd_name == None:
            assert not args
            matches = self.complete_command(part, add_space=True)
        else:
            try:
                command = self.get_command(cmd_name)
            except (NoSuchCommandError, AmbiguousCommandError) as ex:
                # Not a valid command.  No matches
                return None

            matches = command.complete(self, cmd_name, args, part)

        # Massage matches to look like what readline expects
        # (since readline doesn't know about our exact tokenization routine)
        ret = []
        part_len = len(part)
        for match in matches:
            add_space = False
            if isinstance(match, tuple):
                (match, add_space) = match

            # The command should only return strings that start with
            # the specified partial string.  Check just in case, and ignore
            # anything that doesn't match
            if not match.startswith(part):
                # XXX: It would be nice to raise an exception or print a
                # warning somehow, to let the command developer know that they
                # screwed up and we are ignoring some of the results.
                continue

            readline_match = text + tokenize.escape_arg(match[len(part):])
            if add_space:
                readline_match += ' '
            ret.append(readline_match)

        return ret

    def complete_command(self, text, add_space=False):
        matches = [cmd_name for cmd_name in self.commands.keys()
                   if cmd_name.startswith(text)]
        if add_space:
            matches = [(match, True) for match in matches]
        return matches

    def parse_line(self, line):
        """
        cli.parse_line(line) --> (cmd, args)

        Returns a tuple consisting of the command name, and the arguments
        to pass to the command function.  Default behavior is to tokenize the
        line, and return (tokens[0], tokens)
        """
        tokenizer = tokenize.SimpleTokenizer(line)
        tokens = tokenizer.get_tokens()
        return (tokens[0], tokens)

    def parse_partial_line(self, line):
        """
        cli.parse_line(line) --> (cmd, args, partial_arg)

        Returns a tuple consisting of the command name, and the arguments
        to pass to the command function.  Default behavior is to tokenize the
        line, and return (tokens[0], tokens)
        """
        tokenizer = tokenize.SimpleTokenizer(line)
        tokens = tokenizer.get_tokens(stop_at_end=False)
        if tokens:
            cmd_name = tokens[0]
        else:
            cmd_name = None
        return (cmd_name, tokens, tokenizer.get_partial_token())

    def setup_readline(self):
        self._old_completer = readline.get_completer()
        readline.set_completer(self.complete)
        readline.parse_and_bind(self.completekey+": complete")

    def cleanup_readline(self):
        if self._old_completer:
            readline.set_completer(self._old_completer)
        else:
            readline.set_completer(lambda text, state: None)
