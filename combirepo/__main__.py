#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#
# Copyright (C) Samsung Electronics, 2016
#
# 2016         Ilya Palachev                 <i.palachev@samsung.com>
#              Vyacheslav Barinov             <v.barinov@samsung.com>

import os
from commandline_parser import CommandlineParser
from config_parser import ConfigParser
import repository_combiner


def main(args=None):
    commandline_parser = CommandlineParser()
    commandline_parameters = commandline_parser.parse()
    config_parser = ConfigParser()
    if os.path.isfile(config_parser.path):
        config_parameters = config_parser.parse()
        parameters = commandline_parameters + config_parameters
    else:
        parameters = commandline_parameters
    repository_combiner.combine(parameters)


if __name__ == '__main__':
    main()
