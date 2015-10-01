#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This file is based on Oz Nahum Tiram <nahumoz@gmail.com> work
"""
This module builds a standard UNIX manpage from ArgsParse options description
"""

import datetime
from distutils.core import Command
from distutils.errors import DistutilsOptionError
from distutils.command.build import build
import argparse
from os import path, mkdir

AUTO_BUILD = True

INTRO = r""".SS TERMS AND ABBREVIATIONS
.TP
.BR original\\fR\ repository
Repository which is used as base for building - usually contains a repository
which is used for traditional firmware build.
.TP
.BR marked\\fR\ repository
Repository which has changes in build procedure and has packages with certain
uncommon features: Address Sanitizer enabled, LTO switched on and so on.
.TP
.BR kickstart\\fR\ file
A build description script file used by mic tool for firmware creation.
.TP
.BR triplet\\fR
Combination of
.IR \(lqrepository_name\ original_path\ marked_path\(rq \\fR
used for mapping marked repositories to original ones
.TP
.BR config\\fR\ file
A configuration file in format equal to gbs.conf
"""


def check_data_dir():
    """
    Check if combirepo/data directory exists or create it
    """
    data_dir = path.join(path.dirname(path.abspath(__file__)),
                         "combirepo", "data")
    if not path.exists(data_dir):
        mkdir(data_dir)
    return data_dir


class BuildManPage(Command):
    """
    Class with man page generation activities for Command
    """
    description = 'Generate man page from an ArgumentParser instance.'

    user_options = [
        ('output=', 'O', 'output file'),
        ('parser=', None, 'module path to an ArgumentParser instance'
         '(e.g. mymod:func, where func is a method or function which return'
         'an arparse.ArgumentParser instance.'),
    ]

    def initialize_options(self):
        self.output = None
        self.parser = None

    def finalize_options(self):
        if self.output is None:
            raise DistutilsOptionError('\'output\' option is required')
        if self.parser is None:
            raise DistutilsOptionError('\'parser\' option is required')
        mod_name, f_name = self.parser.split(':')
        fromlist = mod_name.split('.')
        mod = __import__(mod_name, fromlist=fromlist)
        self._parser = getattr(mod, f_name)(formatter_class=ManPageFormatter)

        self.announce('Writing man page %s' % self.output)
        self._today = datetime.date.today()

    def run(self):

        dist = self.distribution
        url = dist.get_url()
        appname = self._parser.prog

        sections = {'authors': ("Contact\n"
                                r".MT i.palachev@\:samsung.com\n"
                                "Ilya Palachev\n"
                                r".ME\nor\n.MT v.barinov@\:samsung.com\n"
                                "Vyacheslav Barinov\n.ME\n"
                                "for more information or see {0}".format(url)),
                    'see also': ("mic(1), osc(1), gbs(1),"
                                 "createrepo(8), modifyrepo(1)")}

        dist = self.distribution
        mpf = ManPageFormatter(appname,
                               desc=dist.get_description(),
                               long_desc=dist.get_long_description(),
                               ext_sections=sections)

        man_page = mpf.format_man_page(self._parser)
        check_data_dir()
        with open(self.output, 'w') as man_file:
            man_file.write(man_page)


class ManPageFormatter(argparse.HelpFormatter):
    """
    Formatter class to create man pages.
    This class relies only on the parser, and not distutils.
    The following shows a scenario for usage::

        from pwman import parser_options
        from build_manpage import ManPageFormatter

        # example usage ...

        dist = distribution
        mpf = ManPageFormatter(appname,
                               desc=dist.get_description(),
                               long_desc=dist.get_long_description(),
                               ext_sections=sections)

        # parser is an ArgumentParser instance
        m = mpf.format_man_page(parsr)

        with open(self.output, 'w') as f:
            f.write(m)

    The last line would print all the options and help infomation wrapped with
    man page macros where needed.
    """

    def __init__(self,
                 prog,
                 indent_increment=2,
                 max_help_position=24,
                 width=None,
                 desc=None,
                 long_desc=None,
                 ext_sections=None):

        super(ManPageFormatter, self).__init__("combirepo")

        self._prog = "combirepo"
        self._section = 1
        self._today = datetime.date.today().strftime('%Y\\-%m\\-%d')
        self._desc = desc
        self._long_desc = long_desc
        self._ext_sections = ext_sections

    def _split_lines(self, text, width):
        """
        Allows forcing newlines in lines starting with R|
        """
        if text.startswith('R|'):
            return text[2:].splitlines()
        return argparse.HelpFormatter._split_lines(self, text, width)

    def _get_formatter(self, **kwargs):
        """
        Return current formatter
        """
        return self.formatter_class(prog=self.prog, **kwargs)

    def _markup(self, txt):
        """
        Convert description minuses to groff markup
        """
        return txt.replace('-', '\\-')

    def _underline(self, string):
        """
        groff underlined text markup
        """
        return "\\fI\\s-1" + string + "\\s0\\fR"

    def _bold(self, string):
        """
        groff bold text markup
        """
        if not string.strip().startswith('\\fB'):
            string = '\\fB' + string
        if not string.strip().endswith('\\fR'):
            string = string + '\\fR'
        return string

    def _mk_synopsis(self, parser):
        """
        Create the first section of man page
        """
        self.add_usage(parser.usage, parser._actions,
                       parser._mutually_exclusive_groups, prefix='')
        usage = self._format_usage(None, parser._actions,
                                   parser._mutually_exclusive_groups, '')

        usage = usage.replace('%s ' % self._prog, '')
        usage = '.SH SYNOPSIS\n \\fB%s\\fR %s\n' % (self._markup(self._prog),
                                                    usage)
        return usage

    def _mk_title(self, prog):
        """
        Create the first line of man page
        """
        return '.TH {0} {1} {2}\n'.format(prog, self._section,
                                          self._today)

    def _make_name(self, parser):
        """
        this method is in consitent with others ... it relies on
        distribution
        """
        return '.SH NAME\n%s \\- %s\n' % (parser.prog,
                                          parser.description)

    def _mk_description(self):
        """
        Add long description before options listing
        """
        if self._long_desc:
            long_desc = self._long_desc.replace('\n', '\n.br\n')
            return '.SH DESCRIPTION\n%s\n' % self._markup(long_desc) + INTRO
        else:
            return ''

    def _mk_footer(self, sections):
        """
        Append additional sections to end of man page
        """
        if not hasattr(sections, '__iter__'):
            return ''

        footer = []
        for section, value in sections.items():
            part = ".SH {}\n {}".format(section.upper(), value)
            footer.append(part)

        return '\n'.join(footer)

    def format_man_page(self, parser):
        """
        Creates the man page as a single string object
        """
        page = []
        page.append(self._mk_title(self._prog))
        page.append(self._mk_synopsis(parser))
        page.append(self._mk_description())
        page.append(self._mk_options(parser))
        page.append(self._mk_footer(self._ext_sections))

        return ''.join(page)

    def _mk_options(self, parser):
        """
        Convert ArgsParse options to man page description
        """
        formatter = parser._get_formatter()

        # positionals, optionals and user-defined groups
        for action_group in parser._action_groups:
            formatter.start_section(None)
            formatter.add_text(None)
            formatter.add_arguments(action_group._group_actions)
            formatter.end_section()

        # epilog
        formatter.add_text(parser.epilog)

        # determine help from format above
        return '.SH OPTIONS\n' + formatter.format_help()

    def _format_action_invocation(self, action):
        """
        Format options description into groff
        """
        if not action.option_strings:
            metavar, = self._metavar_formatter(action, action.dest)(1)
            return metavar

        else:
            parts = []

            # if the Optional doesn't take a value, format is:
            #    -s, --long
            if action.nargs == 0:
                parts.extend([self._bold(action_str)
                              for action_str in action.option_strings])

            # if the Optional takes a value, format is:
            #    -s ARGS, --long ARGS
            else:
                default = self._underline(action.dest.upper())
                args_string = self._format_args(action, default)
                for option_string in action.option_strings:
                    parts.append('%s %s' %
                                 (self._bold(option_string), args_string))

            return ', '.join(parts)


if AUTO_BUILD:
    build.sub_commands.append(('build_manpage', None))
