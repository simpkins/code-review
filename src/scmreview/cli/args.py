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

from .exceptions import *
from . import command, tokenize


class ParsedArgs(object):
    pass


class ArgCommand(command.Command):
    def __init__(self, args, help):
        self.arg_types = args
        self.help_text = help

    def run(self, cli_obj, name, args, line):
        args = args[1:]
        num_args = len(args)
        num_arg_types = len(self.arg_types)

        if num_args > num_arg_types:
            trailing_args = args[num_arg_types:]
            msg = 'trailing arguments: ' + tokenize.escape_args(trailing_args)
            raise CommandArgumentsError(msg)

        parsed_args = ParsedArgs()
        for n in range(num_args):
            arg_type = self.arg_types[n]
            value = arg_type.parse(cli_obj, args[n])
            setattr(parsed_args, arg_type.get_name(), value)

        if num_args < num_arg_types:
            # Make sure the remaining options are optional
            # (The next argument must be marked as optional.
            # The optional flag on arguments after this doesn't matter.)
            arg_type = self.arg_types[num_args]
            if not arg_type.is_optional():
                msg = 'missing %s' % (arg_type.get_hr_name(),)
                raise CommandArgumentsError(msg)

        for n in range(num_args, num_arg_types):
            arg_type = self.arg_types[n]
            setattr(parsed_args, arg_type.get_name(),
                    arg_type.get_default_value())

        return self.run_parsed(cli_obj, name, parsed_args)

    def help(self, cli_obj, name, args, line):
        args = args[1:]
        syntax = name
        end = ''
        for arg in self.arg_types:
            if arg.is_optional():
                syntax += ' [<%s>' % (arg.get_name(),)
                end += ']'
            else:
                syntax += ' <%s>' % (arg.get_name(),)
        syntax += end

        cli_obj.output(syntax)
        if not self.help_text:
            return

        # FIXME: do nicer formatting of the help message
        cli_obj.output()
        cli_obj.output(self.help_text)

    def complete(self, cli_obj, name, args, text):
        args = args[1:]
        index = len(args)
        try:
            arg_type = self.arg_types[index]
        except IndexError:
            return []

        return arg_type.complete(cli_obj, text)


class Argument(object):
    def __init__(self, name, **kwargs):
        self.name = name
        self.hr_name = name
        self.default = None
        self.optional = False

        for (kwname, kwvalue) in kwargs.items():
            if kwname == 'default':
                self.default = kwvalue
            elif kwname == 'hr_name':
                self.hr_name = kwvalue
            elif kwname == 'optional':
                self.optional = kwvalue
            else:
                raise TypeError('unknown keyword argument %r' % (kwname,))

    def get_name(self):
        return self.name

    def get_hr_name(self):
        """
        arg.get_hr_name() --> string

        Get the human-readable name.
        """
        return self.hr_name

    def is_optional(self):
        return self.optional

    def get_default_value(self):
        return self.default

    def complete(self, cli_obj, text):
        return []


class StringArgument(Argument):
    def parse(self, cli_obj, arg):
        return arg


class IntArgument(Argument):
    def __init__(self, name, **kwargs):
        self.min = None
        self.max = None

        arg_kwargs = {}
        for (kwname, kwvalue) in kwargs.items():
            if kwname == 'min':
                self.min = kwvalue
            elif kwname == 'max':
                self.max = max
            else:
                arg_kwargs[kwname] = kwvalue

        Argument.__init__(self, name, **arg_kwargs)

    def parse(self, cli_obj, arg):
        try:
            value = int(arg)
        except ValueError:
            msg = '%s must be an integer' % (self.get_hr_name(),)
            raise CommandArgumentsError(msg)

        if self.min != None and value < self.min:
            msg = '%s must be greater than %s' % (self.get_hr_name(), self.min)
            raise CommandArgumentsError(msg)
        if self.max != None and value > self.max:
            msg = '%s must be less than %s' % (self.get_hr_name(), self.max)
            raise CommandArgumentsError(msg)

        return value
