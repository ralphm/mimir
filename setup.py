#!/usr/bin/env python

# Copyright (c) 2005-2008 Ralph Meijer
# See LICENSE for details.

from setuptools import setup
from mimir import __version__

# Make sure 'twisted' doesn't appear in top_level.txt

try:
    from setuptools.command import egg_info
    egg_info.write_toplevel_names
except (ImportError, AttributeError):
    pass
else:
    def _top_level_package(name):
        return name.split('.', 1)[0]

    def _hacked_write_toplevel_names(cmd, basename, filename):
        pkgs = dict.fromkeys(
            [_top_level_package(k)
                for k in cmd.distribution.iter_distribution_names()
                if _top_level_package(k) != "twisted"
            ]
        )
        cmd.write_file("top-level names", filename, '\n'.join(pkgs) + '\n')

    egg_info.write_toplevel_names = _hacked_write_toplevel_names

setup(name='mimir',
      version=__version__,
      description=u'Mimir daemons',
      author='Ralph Meijer',
      author_email='ralphm@ik.nu',
      url='http://mimir.ik.nu/',
      license='MIT',
      packages=[
          'mimir',
          'mimir.aggregator',
          'mimir.aggregator.test',
          'mimir.monitor',
          'twisted.plugins',
      ],
      package_data={'twisted.plugins': ['twisted/plugins/mimir_aggregator.py',
                                        'twisted/plugins/mimir_monitor.py']},
      data_files=[('share/mimir', ['db/monitor.sql'])],
      zip_safe=False,
      install_requires = ['wokkel >= 0.4.0',
                          'simplejson',
                          'FeedParser'],
)

# Make Twisted regenerate the dropin.cache, if possible.  This is necessary
# because in a site-wide install, dropin.cache cannot be rewritten by
# normal users.
try:
    from twisted.plugin import IPlugin, getPlugins
except ImportError:
    pass
else:
    list(getPlugins(IPlugin))
