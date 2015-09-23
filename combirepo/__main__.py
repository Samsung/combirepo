#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
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
        parameters = config_parameters + commandline_parameters
    else:
        parameters = commandline_parameters
    repository_combiner.combine(parameters)


if __name__ == '__main__':
    main()
