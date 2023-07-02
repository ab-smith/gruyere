"""Gruyere Template Language, part of Gruyere, a web application with holes.

Copyright 2017 Google Inc. All rights reserved.

This code is licensed under the https://creativecommons.org/licenses/by-nd/3.0/us/
Creative Commons Attribution-No Derivative Works 3.0 United States license.

DO NOT COPY THIS CODE!

This application is a small self-contained web application with numerous
security holes. It is provided for use with the Web Application Exploits and
Defenses codelab. You may modify the code for your own use while doing the
codelab but you may not distribute the modified code. Brief excerpts of this
code may be used for educational or instructional purposes provided this
notice is kept intact. By using Gruyere you agree to the Terms of Service
https://www.google.com/intl/en/policies/terms/
"""
from __future__ import print_function

from builtins import str
from builtins import range
import collections.abc as collections
__author__ = 'Bruce Leban'

# system modules
import html
import logging
import operator
import os
import pprint
import sys

# our modules
import gruyere
import sanitize


def ExpandTemplate(template, specials, params, name=''):
  """Expands a template.

  Args:
    template: a string template.
    specials: a dict of special values.
    params: a dict of parameter values.
    name: the name of the _this object.

  Returns:
    the expanded template.

  The template language includes these block structures:

    [[include:<filename>]] ...[[/include:<filename>]]
      Insert the file or if the file cannot be opened insert the contents of
      the block. The path should use / as a separator regardless of what
      the underlying operating system is.

    [[for:<variable>]] ... [[/for:<variable>]]
      Iterate over the variable (which should be a mapping or sequence) and
      insert the block once for each value. Inside the loop _key is bound to
      the key value for the iteration.

    [[if:<variable>]] ... [[/if:<variable>]]
      Expand the contents of the block if the variable is not 'false'.  There
      is no else; use [[if:!<variable>]] instead.

    Note that in each case the end tags must match the begin tags with a
    leading slash. This prevents mismatched tags and makes it easier to parse.

  The variable syntax is:

    {{<field>[.<field>]*[:<escaper>]}}

  where <field> is:

    a key to extract from a mapping
    a number to extract from a sequence

  Variable names that start with '_' are special values:
    _key = iteration key (inside loops)
    _this = iteration value (inside loop)
    _db = the database
    _cookie = the user's cookie
    _profile = the user's profile ~ _db.*(_cookie.user)

  If a field name starts with '*' it refers to a dereferenced parameter (orx
  *_this). For example, _db.*uid retrieves the entry from _db matching the
  uid parameter.

  The comment syntax is:

    {{#<comment>}}
  """
  t = _ExpandBlocks(str(template), specials, params, name)
  t = _ExpandVariables(t, specials, params, name)
  return t


BLOCK_OPEN = '[['
END_BLOCK_OPEN = '[[/'
BLOCK_CLOSE = ']]'


def _ExpandBlocks(template, specials, params, name):
  """Expands all the blocks in a template."""
  result = []
  rest = template
  while rest:
    tag, before_tag, after_tag = _FindTag(rest, BLOCK_OPEN, BLOCK_CLOSE)
    if tag is None:
      break
    end_tag = END_BLOCK_OPEN + tag + BLOCK_CLOSE
    before_end = rest.find(end_tag, after_tag)
    if before_end < 0:
      break
    after_end = before_end + len(end_tag)

    result.append(rest[:before_tag])
    block = rest[after_tag:before_end]
    result.append(_ExpandBlock(tag, block, specials, params, name))
    rest = rest[after_end:]
  return ''.join(result) + rest


VAR_OPEN = '{{'
VAR_CLOSE = '}}'


def _ExpandVariables(template, specials, params, name):
  """Expands all the variables in a template."""
  result = []
  rest = template
  while rest:
    tag, before_tag, after_tag = _FindTag(rest, VAR_OPEN, VAR_CLOSE)
    if tag is None:
      break
    result.append(rest[:before_tag])
    result.append(str(_ExpandVariable(tag, specials, params, name)))
    rest = rest[after_tag:]
  return ''.join(result) + rest


FOR_TAG = 'for'
IF_TAG = 'if'
INCLUDE_TAG = 'include'


def _ExpandBlock(tag, template, specials, params, name):
  """Expands a single template block."""

  tag_type, block_var = tag.split(':', 1)
  if tag_type == INCLUDE_TAG:
    return _ExpandInclude(tag, block_var, template, specials, params, name)
  elif tag_type == IF_TAG:
    block_data = _ExpandVariable(block_var, specials, params, name)
    if block_data:
      return ExpandTemplate(template, specials, params, name)
    return ''
  elif tag_type == FOR_TAG:
    block_data = _ExpandVariable(block_var, specials, params, name)
    return _ExpandFor(tag, template, specials, block_data)
  else:
    _Log('Error: Invalid block: %s' % (tag,))
    return ''


def _ExpandInclude(_, filename, template, specials, params, name):
  """Expands an include block (or insert the template on an error)."""
  result = ''
  # replace /s with local file system equivalent
  fname = os.sep + filename.replace('/', os.sep)
  f = None
  try:
    try:
      f = gruyere._Open(gruyere.RESOURCE_PATH, fname)
      result = f.read()
    except IOError:
      _Log('Error: missing filename: %s' % (filename,))
      result = template
  finally:
    if f: f.close()
  return ExpandTemplate(result, specials, params, name)


def _ExpandFor(tag, template, specials, block_data):
  """Expands a for block iterating over the block_data."""
  result = []
  if isinstance(block_data, collections.Mapping):
    for v in block_data:
      result.append(ExpandTemplate(template, specials, block_data[v], v))
  elif isinstance(block_data, collections.Sequence):
    for i in range(len(block_data)):
      result.append(ExpandTemplate(template, specials, block_data[i], str(i)))
  else:
    _Log('Error: Invalid type: %s' % (tag,))
    return ''
  return ''.join(result)


def _ExpandVariable(var, specials, params, name, default=''):
  """Gets a variable value."""
  if var.startswith('#'):  # this is a comment.
    return ''

  # Strip out leading ! which negates value
  inverted = var.startswith('!')
  if inverted:
    var = var[1:]

  # Strip out trailing :<escaper>
  escaper_name = None
  if var.find(':') >= 0:
    (var, escaper_name) = var.split(':', 1)

  value = _ExpandValue(var, specials, params, name, default)
  if inverted:
    value = not value

  if escaper_name == 'text':
    value = html.escape(str(value))
  elif escaper_name == 'html':
    value = sanitize.SanitizeHtml(str(value))
  elif escaper_name == 'pprint':  # for debugging
    value = '<pre>' + cgi.escape(pprint.pformat(value)) + '</pre>'

  if value is None:
    value = ''
  return value


def _ExpandValue(var, specials, params, name, default):
  """Expand one value.

  This expands the <field>.<field>...<field> part of the variable
  expansion. A field may be of the form *<param> to use the value
  of a parameter as the field name.
  """
  if var == '_key':
    return name
  elif var == '_this':
    return params
  if var.startswith('_'):
    value = specials
  else:
    value = params

  for v in var.split('.'):
    if v == '*_this':
      v = params
    if v.startswith('*'):
      v = _GetValue(specials['_params'], v[1:])
      if isinstance(v, collections.Sequence):
        v = v[0]  # reduce repeated url param to single value
    value = _GetValue(value, str(v), default)
  return value


def _GetValue(collection, index, default=''):
  """Gets a single indexed value out of a collection.

  The index is either a key in a mapping or a numeric index into
  a sequence.

  Returns:
    value
  """
  if isinstance(collection, collections.Mapping) and index in collection:
    value = collection[index]
  elif (isinstance(collection, collections.Sequence) and index.isdigit() and
        int(index) < len(collection)):
    value = collection[int(index)]
  else:
    value = default
  return value


def _Cond(test, if_true, if_false):
  """Substitute for 'if_true if test else if_false' in Python 2.4."""
  if test:
    return if_true
  else:
    return if_false


def _FindTag(template, open_marker, close_marker):
  """Finds a single tag.

  Args:
    template: the template to search.
    open_marker: the start of the tag (e.g., '{{').
    close_marker: the end of the tag (e.g., '}}').

  Returns:
    (tag, pos1, pos2) where the tag has the open and close markers
    stripped off and pos1 is the start of the tag and pos2 is the end of
    the tag. Returns (None, None, None) if there is no tag found.
  """
  open_pos = template.find(open_marker)
  close_pos = template.find(close_marker, open_pos)
  if open_pos < 0 or close_pos < 0 or open_pos > close_pos:
    return (None, None, None)
  return (template[open_pos + len(open_marker):close_pos],
          open_pos,
          close_pos + len(close_marker))


def _Log(message):
  logging.warning('%s', message)
  print(message, file=sys.stderr)
