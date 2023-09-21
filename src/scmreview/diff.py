#!/usr/local/bin/python -tt
#
# Copyright 2010 Facebook, Inc.
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
import re
import sys


class DiffParseError(Exception):
    def __init__(self, msg, line_num):
        Exception.__init__(self)
        self.message = msg
        self.line_number = line_num

    def __str__(self):
        return "line %d: %s" % (self.line_number, self.message)


def _adjust_index(i, length, dflt):
    """
    Helper for implementing __getitem__()
    """
    if i is None:
        return dflt

    if i > length:
        return length
    if i < 0:
        adjusted = length + i
        if adjusted < 0:
            raise IndexError(i)
        return adjusted
    return i


def debug(msg):
    # Comment this line out to enable debug messages
    return
    print >> sys.stderr, "DBG:", msg


class Range(object):
    def __init__(self, start, end):
        assert end >= start
        # First line in the range (inclusive)
        self.start = start
        # First line not in the range
        self.end = end

    def __len__(self):
        return self.end - self.start

    def __nonzero__(self):
        return self.end > self.start

    def __getitem__(self, i):
        mylen = len(self)
        if isinstance(i, slice):
            if i.step != None and i.step != 1:
                raise IndexError("non-contiguous slices are not allowed")
            start = _adjust_index(i.start, mylen, 0)
            stop = _adjust_index(i.stop, mylen, mylen)
        else:
            assert isinstance(i, (int, long))
            start = _adjust_index(i, mylen, None)
            if start >= mylen:
                raise IndexError(i)
            stop = start + 1

        return Range(self.start + start, self.start + stop)

    def __str__(self):
        return "(%d,%d)" % (self.start, self.end)

    def format_unified(self):
        """
        Format a string representation of this range for use in a unified diff.

        Unified diffs print the range as <start>,<length>.
        The length may be omitted if it is 1.
        """
        if self.end == self.start + 1:
            # 1-length ranges are represented with just a single number
            return "%d" % (self.start,)
        else:
            assert self.end >= self.start
            return "%d,%d" % (self.start, self.end - self.start)

    @staticmethod
    def parse_unified(value):
        """
        Parse a Range object from a unified diff string.

        May raise ValueError if the string is malformatted.
        """
        components = value.split(",")
        if len(components) == 1:
            # If the range has just a single entry, it comprises a single line.
            first = int(components[0])
            length = 1
        elif len(components) == 2:
            # If the range has two entries, it is the start plus a length.
            first = int(components[0])
            length = int(components[0])
        else:
            raise ValueError("invalid range string %r" % (value,))

        return Range(first, first + length)


class Section(object):
    TYPE_REMOVED = "-"
    TYPE_ADDED = "+"
    TYPE_CONTEXT = " "

    def __init__(self, type):
        self.type = type
        self.old_range = Range(0, 0)
        self.new_range = Range(0, 0)
        self.lines = []

    def __len__(self):
        return len(self.lines)

    def __getitem__(self, i):
        mylen = len(self.lines)
        if isinstance(i, slice):
            if i.step != None and i.step != 1:
                raise IndexError("non-contiguous slices are not allowed")
            start = _adjust_index(i.start, mylen, 0)
            stop = _adjust_index(i.stop, mylen, mylen)
        else:
            assert isinstance(i, (int, long))
            start = _adjust_index(i, mylen, None)
            if start >= mylen:
                raise IndexError(i)
            stop = start + 1

        section = Section(self.type)
        section.lines = self.lines[start:stop]
        if self.old_range:
            section.old_range = self.old_range[start:stop]
        else:
            section.old_range = self.old_range[:]
        if self.new_range:
            section.new_range = self.new_range[start:stop]
        else:
            section.new_range = self.new_range[:]

        return section

    def head(self, length):
        return self[:length]

    def tail(self, length):
        return self[-length:]


class SectionIterator(object):
    """
    An iterator to iterate over contiguous sections of a hunk.

    Each call to next() returns a section of added, removed, or context lines.
    """

    def __init__(self, hunk):
        self.hunk = hunk
        self.index = 0
        self.old_line = hunk.old_range.start
        self.new_line = hunk.new_range.start

    def __iter__(self):
        return self

    def next(self):
        hunk_len = len(self.hunk.lines)
        if self.index >= hunk_len:
            raise StopIteration()

        line = self.hunk.lines[self.index]
        section = Section(line[0])
        section.lines.append(line)
        self.index += 1

        while self.index < hunk_len:
            line = self.hunk.lines[self.index]
            if line[0] != section.type:
                break

            section.lines.append(line)
            self.index += 1

        num_lines = len(section.lines)
        if section.type == Section.TYPE_REMOVED:
            old_end = self.old_line + num_lines
            new_end = self.new_line
        elif section.type == Section.TYPE_ADDED:
            old_end = self.old_line
            new_end = self.new_line + num_lines
        elif section.type == Section.TYPE_CONTEXT:
            old_end = self.old_line + num_lines
            new_end = self.new_line + num_lines

        section.old_range = Range(self.old_line, old_end)
        section.new_range = Range(self.new_line, new_end)
        self.old_line = old_end
        self.new_line = new_end

        return section


class Hunk(object):
    """
    A diff hunk.
    """

    def __init__(self, old_range, new_range):
        self.old_range = old_range
        self.new_range = new_range
        # Every line in self.lines should start with either '+', '-', or ' '
        self.lines = []

    def section_iter(self):
        return SectionIterator(self)

    def split(self, context):
        """
        Split a hunk into one or more hunks, with a smaller amount of context.
        """
        hunks = []

        current = None

        debug("split:")
        for section in self.section_iter():
            debug("  -%s +%s" % (section.old_range, section.new_range))
            if section.type == Section.TYPE_CONTEXT:
                num_lines = len(section.lines)
                if current is None:
                    # This is the start of the first hunk
                    if num_lines > context:
                        # Some of the initial context should be trimmed
                        current = [section.tail(context)]
                        debug(
                            "    trimmed to -%s +%s"
                            % (current[0].old_range, current[0].new_range)
                        )
                    else:
                        current = [section]
                else:
                    if num_lines > context * 2:
                        # This context section is large enough for us to split
                        current.append(section.head(context))
                        debug(
                            "    split: -%s +%s"
                            % (current[-1].old_range, current[-1].new_range)
                        )
                        hunk = Hunk.from_section_list(current)
                        hunks.append(hunk)
                        current = [section.tail(context)]
                        debug(
                            "           -%s +%s"
                            % (current[0].old_range, current[0].new_range)
                        )
                    else:
                        # Can't split, just append this section
                        current.append(section)
            else:
                if current is None:
                    current = []
                current.append(section)

        assert current is not None  # non-empty hunks are not allowed
        # Create a hunk from the sections remaining in current.
        if len(current) == 1 and current[0].type == Section.TYPE_CONTEXT:
            # This is just a context section that was split from the end of the
            # last set of changes.  Don't add a hunk of just context.
            pass
        else:
            # Strip the last context section down to the correct number of
            # lines.  All internal context sections may have up to 2x the
            # number of context lines, but the last one should not have more
            # than the specified number of context lines.
            if current[-1].type == Section.TYPE_CONTEXT:
                current[-1] = section.head(context)
            hunk = Hunk.from_section_list(current)
            hunks.append(hunk)

        return hunks

    @staticmethod
    def from_section_list(sections):
        old_start = sections[0].old_range.start
        new_start = sections[0].new_range.start

        old_index = old_start
        new_index = new_start
        lines = []
        for section in sections:
            assert section.old_range.start == old_index
            assert section.new_range.start == new_index
            old_index = section.old_range.end
            new_index = section.new_range.end
            lines.extend(section.lines)

        old_range = Range(old_start, old_index)
        new_range = Range(new_start, new_index)
        hunk = Hunk(old_range, new_range)
        hunk.lines = lines

        return hunk


class FileSection(object):
    def __init__(self, old_path, new_path):
        self.old_path = old_path
        self.new_path = new_path
        self.hunks = []


class Diff(object):
    def __init__(self):
        self.files = []


class UnifiedDiffParser(object):
    def __init__(self, input):
        self.input = input
        self.line_num = 0
        self.diff = Diff()

        self.old_filename_re = re.compile(r"^--- (.*)$")
        self.new_filename_re = re.compile(r"^\+\+\+ (.*)$")
        self.hunk_re = re.compile(r"^@@ -(.*) \+(.*) @@$")

        self.eofError = "no diff information read"

    def parse(self):
        try:
            self.parse_internal()
        except StopIteration:
            # StopIteration is raised when we hit end of input.
            # If we are currently in a state where EOF is not expected,
            # self.eofError will contain an error message.  Otherwise,
            # self.eofError will be None.
            if self.eofError != None:
                self.parse_error("unexpected end of input: " + str(self.eofError))

        return self.diff

    def parse_internal(self):
        self.expect_file_header()

        while True:
            line = self.next_line()
            if line.startswith("@@"):
                self.parse_hunk_start(line)
                continue

            if line.startswith("-") or line.startswith("+") or line.startswith(" "):
                # removed, added, or context line
                current_hunk = self.diff.files[-1].hunks[-1]
                current_hunk.lines.append(line)
                continue

            m = self.old_filename_re.match(line)
            if m:
                # new file section
                self.parse_file_header(match)
                continue

            # Unknown line; probably a header before the next file.
            # Skip over any other header lines, and parse the next
            # file information.
            self.expect_file_header()

    def expect_file_header(self):
        # Skip over any non-diff header lines, and read
        # to the next file section.
        while True:
            line = self.next_line()
            m = self.old_filename_re.match(line)
            if m:
                # Saw the old file path
                break

            # Unknown line.  Make sure it doesn't look like a valid diff line.
            # (Normally this is just a header printed out in between files.
            # git and subversion print such headers.)
            if (
                line.startswith("-")
                or line.startswith("+")
                or line.startswith(" ")
                or line.startswith("@@")
            ):
                self.parse_error("unexpected diff line after non-diff section")

        # We found the start of the next file.  Parse the file header
        self.parse_file_header(m)

    def parse_file_header(self, match):
        # Extract the old path from the match
        old_path = match.group(1)

        # Read the new path
        self.eofError = "expected new filename"
        line = self.next_line()
        match = self.new_filename_re.match(line)
        if not match:
            self.parse_error(self.eofError)
        new_path = match.group(1)

        self.diff.files.append(FileSection(old_path, new_path))

        # Read the start of the first hunk
        self.eofError = "expected hunk start"
        line = self.next_line()
        if not line.startswith("@@"):
            self.parse_error(self.eofError)
        self.parse_hunk_start(line)

        self.eofError = None

    def next_line(self):
        line = self.input.next()
        self.line_num += 1

        # TODO: it would be nice to warn if there is no newline
        # at the end of the file
        if line.endswith("\n"):
            line = line[:-1]
        return line

    def parse_hunk_start(self, line):
        m = self.hunk_re.match(line)
        if not m:
            self.parse_error("malformed hunk start line")

        old_range = self.parse_range(m.group(1))
        new_range = self.parse_range(m.group(2))

        hunk = Hunk(old_range, new_range)
        self.diff.files[-1].hunks.append(hunk)

    def parse_range(self, value):
        try:
            return Range.parse_unified(value)
        except ValueError:
            self.parse_error("invalid range %r" % (value,))

    def parse_error(self, msg):
        raise DiffParseError(msg, self.line_num)


class UnifiedDiffFormatter(object):
    def __init__(self, output):
        self.output = output

    def write(self, diff):
        for file in diff.files:
            self.writeFile(file)

    def writeFile(self, file):
        self.output.write("--- %s\n" % (file.old_path,))
        self.output.write("+++ %s\n" % (file.new_path,))
        for hunk in file.hunks:
            self.writeHunk(hunk)

    def writeHunk(self, hunk):
        self.output.write(
            "@@ -%s +%s @@\n"
            % (hunk.old_range.format_unified(), hunk.new_range.format_unified())
        )
        for line in hunk.lines:
            self.output.write(line)
            self.output.write("\n")
