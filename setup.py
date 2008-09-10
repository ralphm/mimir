#!/usr/bin/env python

# Copyright (c) 2005-2008 Ralph Meijer
# See LICENSE for details.

from setuptools import setup
from mimir import __version__

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
