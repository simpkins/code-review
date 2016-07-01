==========
code-review
==========

code-review is a tool for reviewing diffs in a git or mercurial repository.

It provides a simple CLI for stepping through the modified files, and viewing
the differences with an external diff tool.  This is very convenient if you
prefer using an interactive side-by-side diff viewer.  Although you could also
use the ``GIT_EXTERNAL_DIFF`` environment variable with ``git diff``,
code-review provides much more flexibility for moving between files and
selecting which versions to diff.

Installation
============
From the root of the source tree, run::

    $ python setup.py install

Also see the ``INSTALL`` file.

Setup
=====
codet-review uses ``vimdiff`` by default.  You may set the ``CODE_REVIEW_DIFF``
environment variable to point to your favourite diff program.

Usage
=====
Enter ``code-review -?`` to see the help message. Here are some examples:

To diff commit_a (descendent) against commit_b (ancestor)::

    $ code-review <commit_b> <commit_a>

To diff the working tree against commit_a::

    $ code-review <commit_a>

To diff the index against commit_a::

    $ code-review --cached <commit_a>

To diff a particular commit against its immediate parent::

    $ code-review -c <commit>

Once code-review is running, you should see a prompt menu.  By default, it goes
through all the changed files and show the diff one by one.  You can enter
``?`` to see all available commands.  The prompt also accepts unambiguous
command prefixes.  Here is an example of a review session::

    [dsom:code-review]$ code-review HEAD^
    Now processing modified file README.rst
    README.rst [diff]> l
    0: M README.rst
    1: M setup.py
    2: M src/code-review
    README.rst [diff]> go 2
    Now processing modified file src/code-review
    code-review [diff]> d
    code-review [quit]>
