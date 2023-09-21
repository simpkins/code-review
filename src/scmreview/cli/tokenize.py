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
import re


class TokenizationError(Exception):
    pass


class PartialTokenError(TokenizationError):
    def __init__(self, token, msg):
        TokenizationError.__init__(self, msg)
        self.token = token
        self.error = msg


class State(object):
    def handle_char(self, tokenizer, char):
        raise NotImplementedError()

    def handle_end(self, tokenizer):
        raise NotImplementedError()


class EscapeState(State):
    def handle_char(self, tokenizer, char):
        tokenizer.add_to_token(char)
        tokenizer.pop_state()

    def handle_end(self, tokenizer):
        # XXX: We could treat this as an indication to continue on to the next
        # line.
        msg = "unterminated escape sequence"
        raise PartialTokenError(tokenizer.get_partial_token(), msg)


class QuoteState(State):
    def __init__(self, quote_char, escape_chars="\\"):
        State.__init__(self)
        self.quote = quote_char
        self.escape_chars = escape_chars

    def handle_char(self, tokenizer, char):
        if char == self.quote:
            tokenizer.pop_state()
        elif char in self.escape_chars:
            tokenizer.push_state(EscapeState())
        else:
            tokenizer.add_to_token(char)

    def handle_end(self, tokenizer):
        msg = "unterminated quote"
        raise PartialTokenError(tokenizer.get_partial_token(), msg)


class NormalState(State):
    def __init__(self):
        State.__init__(self)
        self.quote_chars = "\"'"
        self.escape_chars = "\\"
        self.delim_chars = " \t\n"

    def handle_char(self, tokenizer, char):
        if char in self.escape_chars:
            tokenizer.push_state(EscapeState())
        elif char in self.quote_chars:
            tokenizer.add_to_token("")
            tokenizer.push_state(QuoteState(char, self.escape_chars))
        elif char in self.delim_chars:
            tokenizer.end_token()
        else:
            tokenizer.add_to_token(char)

    def handle_end(self, tokenizer):
        tokenizer.end_token()


class Tokenizer(object):
    """
    A class for tokenizing strings.

    It isn't particularly efficient.  Performance-wise, it is probably quite
    slow.  However, it is intended to be very customizable.  It provides many
    hooks to allow subclasses to override and extend its behavior.
    """

    STATE_NORMAL = 0
    STATE_IN_QUOTE = 1

    def __init__(self, state, value):
        self.value = value
        self.index = 0
        self.end = len(self.value)

        if isinstance(state, list):
            self.state_stack = state[:]
        else:
            self.state_stack = [state]

        self.current_token = None
        self.tokens = []

        self._processed_end = False

    def get_tokens(self, stop_at_end=True):
        tokens = []

        while True:
            token = self.get_next_token(stop_at_end)
            if token == None:
                break
            tokens.append(token)

        return tokens

    def get_next_token(self, stop_at_end=True):
        # If we don't currently have any tokens to process,
        # call self.process_next_char()
        while not self.tokens:
            if (not stop_at_end) and self.index >= self.end:
                # If stop_at_end is True, we let process_next_char()
                # handle the end of string as normal.  However, if stop_at_end
                # is False, the string value we have received so far is partial
                # (the caller might append more to it later), so return None
                # here without handling the end of the string.
                return None
            if self._processed_end:
                # If there are no more tokens and we've already reached
                # the end of the string, return None
                return None
            self.process_next_char()

        return self._pop_token()

    def _pop_token(self):
        token = self.tokens[0]
        del self.tokens[0]
        return token

    def get_partial_token(self):
        return self.current_token

    def process_next_char(self):
        if self.index >= self.end:
            if self._processed_end:
                raise IndexError()
            self._processed_end = True
            state = self.state_stack[-1]
            state.handle_end(self)
            return

        char = self.value[self.index]
        self.index += 1

        state = self.state_stack[-1]
        state.handle_char(self, char)

    def push_state(self, state):
        self.state_stack.append(state)

    def pop_state(self):
        self.state_stack.pop()
        if not self.state_stack:
            raise Exception("cannot pop last state")

    def add_to_token(self, char):
        if self.current_token == None:
            self.current_token = char
        else:
            self.current_token += char

    def end_token(self):
        if self.current_token == None:
            return

        self.tokens.append(self.current_token)
        self.current_token = None


class SimpleTokenizer(Tokenizer):
    def __init__(self, value):
        Tokenizer.__init__(self, [NormalState()], value)


def escape_arg(arg):
    """
    escape_arg(arg) --> escaped_arg

    This performs string escaping that can be used with SimpleTokenizer.
    (It isn't sufficient for passing strings to a shell.)
    """
    if arg.find('"') >= 0:
        if arg.find("'") >= 0:
            s = re.sub(r"\\", r"\\\\", arg)
            s = re.sub("'", "\\'", s)
            return "'%s'" % (s,)
        else:
            return "'%s'" % (arg,)
    elif arg.find("'") >= 0:
        return '"%s"' % (arg,)
    else:
        return arg


def escape_args(args):
    return " ".join([escape_arg(a) for a in args])
