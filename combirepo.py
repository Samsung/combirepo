#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
from combirepo.commandline_parser import CommandlineParser
from combirepo.config_parser import ConfigParser
import combirepo.repository_combiner


if __name__ == '__main__':
    commandline_parser = CommandlineParser()
    commandline_properties = commandline_parser.parse()
    config_parser = ConfigParser()
    if os.path.isfile(config_parser.path):
        config_properties = config_parser.parse()
        properties = config_properties + commandline_properties
    else:
        properties = commandline_properties
    combirepo.repository_combiner.combine(properties)
