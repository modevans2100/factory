External Python Package: enum34
===============================

This is copied from [enum34 1.1.6](https://pypi.python.org/pypi/enum34).

The dependency to enum34 is recently added to factory toolkit dependency while
most test images still do not have it yet.

To prevent breaking existing systems with a better transition, we'd like to
temporarily make a copy in py_pkg (which was already contained in PAR) so
systems without enum34 installed can still run.