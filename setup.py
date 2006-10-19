#!/usr/bin/env python

# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details.

from distutils.core import setup

setup(name='mimir',
      version='0.3.0',
      description='Mimir daemons',
      author='Ralph Meijer',
      author_email='ralphm@ik.nu',
      url='http://mimir.ik.nu/',
      license='MIT',
      packages=[
          'mimir',
          'mimir.aggregator',
          'mimir.common',
          'mimir.monitor',
          'twisted.plugins',
      ],
      package_data={'twisted.plugins': ['twisted/plugins/mimir_aggregator.py',
                                        'twisted/plugins/mimir_monitor.py']},
      data_files=[('share/mimir', ['db/monitor.sql'])],
)
