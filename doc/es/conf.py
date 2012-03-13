# -*- coding: utf-8 -*-
#
# Bazaar documentation build configuration file, created by
# sphinx-quickstart on Tue Jul 21 17:04:52 2009.
#
# This file is execfile()d with the current directory set to its containing dir.

import sys, os

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
sys.path = [os.path.abspath('../..')] + sys.path

# Most of the configuration for Bazaar docs is defined here ...
from bzrlib.doc_generate.conf import *


## Configuration specific to this site ##

# The locale code for this documentation set
bzr_locale = 'es'

# Translations & supporting helper function
bzr_titles = {
        u'Table of Contents (%s)': u'Contenidos (%s)',
        u'Bazaar User Guide': u'Guia de Usuario',
        u'Bazaar User Reference': None,
        u'Bazaar Release Notes': None,
        u'Bazaar Upgrade Guide': None,
        u'Bazaar in five minutes': u'Bazaar en cinco minutos',
        u'Bazaar Tutorial': None,
        u'Using Bazaar With Launchpad': None,
        u'Centralized Workflow Tutorial': None,
    }
def bzr_title(s):
    return bzr_titles.get(s) or s

# The language for content autogenerated by Sphinx. Refer to documentation
# for a list of supported languages.
language = bzr_locale

# A shorter title for the navigation bar.  Default is the same as html_title.
html_short_title = bzr_title(u"Table of Contents (%s)") % (release,)

# Additional templates that should be rendered to pages, maps page names to
# template names.
#html_additional_pages = {'index': 'index.html'}

# Output file base name for HTML help builder.
htmlhelp_basename = 'bzr-%s' % (bzr_locale,)

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title, author, documentclass [howto/manual]).
bzr_documents = [
  # Manuals
  ('user-guide/index', 'bzr-%s-user-guide' % (bzr_locale,),
    bzr_title(u'Bazaar User Guide'), bzr_team, 'manual'),
  #('user-reference/bzr_man', 'bzr-%s-user-reference' % (bzr_locale,),
  #  bzr_title(u'Bazaar User Reference'), bzr_team, 'manual'),
  #('release-notes/NEWS', 'bzr-%s-release-notes' % (bzr_locale,),
  #  bzr_title(u'Bazaar Release Notes'), bzr_team, 'manual'),
  #('upgrade-guide/index', 'bzr-%s-upgrade-guide' % (bzr_locale,),
  #  bzr_title(u'Bazaar Upgrade Guide'), bzr_team, 'manual'),
  # Tutorials
  ('mini-tutorial/index', 'bzr-%s-tutorial-mini' % (bzr_locale,),
    bzr_title(u'Bazaar in five minutes'), bzr_team, 'howto'),
  #('tutorials/tutorial', 'bzr-%s-tutorial' % (bzr_locale,),
  #  bzr_title(u'Bazaar Tutorial'), bzr_team, 'howto'),
  #('tutorials/using_bazaar_with_launchpad',
  #  'bzr-%s-tutorial-with-launchpad' % (bzr_locale,),
  #  bzr_title(u'Using Bazaar With Launchpad'), bzr_team, 'howto'),
  #('tutorials/centralized_workflow',
  #  'bzr-%s-tutorial-centralized' % (bzr_locale,),
  #  bzr_title(u'Centralized Workflow Tutorial'), bzr_team, 'howto'),
]

latex_documents = [
    (start, target+'.tex', title, author, doc_class)
    for start, target, title, author, doc_class in bzr_documents
    ]

texinfo_documents = [
    (start, target, title, author, doc_class)
    for start, target, title, author, doc_class in bzr_documents
    ]

# List of documents that shouldn't be included in the build.
unused_docs = [
    # Subtopics that get included
    'upgrade-guide/overview',
    'upgrade-guide/data_migration',
    'upgrade-guide/tips_and_tricks',
    'user-guide/resolving_conflicts',
    'user-guide/version_info',
    # Plain-style documentation generation stuff
    'user-guide/index-plain',
]

