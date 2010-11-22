==========
git-review
==========

git-review is a tool for reviewing diffs in a git repository.

It provides a simple CLI for stepping through the modified files, and viewing
the differences with an external diff tool.  This is very convenient if you
prefer using an interactive side-by-side diff viewer.  Although you could also
use the ``GIT_EXTERNAL_DIFF`` environment variable with ``git diff``,
git-review provides much more flexibility for moving between files and
selecting which versions to diff.

Installation
============
From the root of the source tree, run::

    $ python setup.py install

Also see the ``INSTALL`` file.

Setup
=====
git-review uses ``vimdiff`` by default.  You may set the ``GIT_REVIEW_DIFF``
environment variable to point to your favourite diff program.

Usage
=====
Enter ``git-review -?`` to see the help message. Here are some examples:

To diff commit_a (descendent) against commit_b (ancestor)::

    $ git-review <commit_b> <commit_a>

To diff the working tree against commit_a::

    $ git-review <commit_a>

To diff the index against commit_a::

    $ git-review --cached <commit_a>

To diff a particular commit against its immediate parent::

    $ git-review -c <commit>

Once git-review is running, you should see a prompt menu.  By default, it goes
through all the changed files and show the diff one by one.  You can enter
``?`` to see all available commands.  The prompt also accepts unambiguous
command prefixes.  Here is an example of a review session::

    [dsom:git-review]$ git-review HEAD^
    Now processing modified file README.rst
    README.rst [diff]> l
    0: M README.rst
    1: M setup.py
    2: M src/git-review
    README.rst [diff]> go 2
    Now processing modified file src/git-review
    git-review [diff]> d
    git-review [quit]>
