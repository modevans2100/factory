#!/usr/bin/env python
# pylint: disable=C0301
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# This is a required test to check all VPD related information.


"""Collection of valid VPD values for ChromeOS."""

# Keys that may not be logged.
VPD_BLACKLIST_KEYS = [
  'ubind_attribute',
  'gbind_attribute'
]
REDACTED = 'REDACTED'
def FilterVPD(vpd_map):
  '''Replaces values of any keys in VPD_BLACKLIST_KEYS with REDACTED.'''
  return dict((k, REDACTED if k in VPD_BLACKLIST_KEYS else v)
              for k, v in vpd_map.iteritems())


# keyboard_layout: https://gerrit.chromium.org/gerrit/gitweb?p=chromium/src.git;a=blob;f=chrome/browser/chromeos/input_method/input_methods.txt
KEYBOARD_LAYOUT = [
  'xkb:nl::nld',
  'xkb:be::nld',
  'xkb:fr::fra',
  'xkb:be::fra',
  'xkb:ca::fra',
  'xkb:ch:fr:fra',
  'xkb:de::ger',
  'xkb:de:neo:ger',
  'xkb:be::ger',
  'xkb:ch::ger',
  'xkb:jp::jpn',
  'xkb:ru::rus',
  'xkb:ru:phonetic:rus',
  'xkb:us::eng',
  'xkb:us:intl:eng',
  'xkb:us:altgr-intl:eng',
  'xkb:us:dvorak:eng',
  'xkb:us:colemak:eng',
  'xkb:br::por',
  'xkb:bg::bul',
  'xkb:bg:phonetic:bul',
  'xkb:ca:eng:eng',
  'xkb:cz::cze',
  'xkb:ee::est',
  'xkb:es::spa',
  'xkb:es:cat:cat',
  'xkb:dk::dan',
  'xkb:gr::gre',
  'xkb:il::heb',
  'xkb:kr:kr104:kor',
  'xkb:latam::spa',
  'xkb:lt::lit',
  'xkb:lv:apostrophe:lav',
  'xkb:hr::scr',
  'xkb:gb:extd:eng',
  'xkb:gb:dvorak:eng',
  'xkb:fi::fin',
  'xkb:hu::hun',
  'xkb:it::ita',
  'xkb:no::nob',
  'xkb:pl::pol',
  'xkb:pt::por',
  'xkb:ro::rum',
  'xkb:se::swe',
  'xkb:sk::slo',
  'xkb:si::slv',
  'xkb:rs::srp',
  'xkb:tr::tur',
  'xkb:ua::ukr',
  ]

# initial_locale: http://git.chromium.org/gitweb/?p=chromium.git;a=blob;f=ui/base/l10n/l10n_util.cc
INITIAL_LOCALE = [
  "af",
  "am",
  "ar",
  "az",
  "be",
  "bg",
  "bh",
  "bn",
  "br",
  "bs",
  "ca",
  "co",
  "cs",
  "cy",
  "da",
  "de",
  "de-AT",
  "de-CH",
  "de-DE",
  "el",
  "en",
  "en-AU",
  "en-CA",
  "en-GB",
  "en-NZ",
  "en-US",
  "en-ZA",
  "eo",
  "es",
  "es-419",
  "et",
  "eu",
  "fa",
  "fi",
  "fil",
  "fo",
  "fr",
  "fr-CA",
  "fr-CH",
  "fr-FR",
  "fy",
  "ga",
  "gd",
  "gl",
  "gn",
  "gu",
  "ha",
  "haw",
  "he",
  "hi",
  "hr",
  "hu",
  "hy",
  "ia",
  "id",
  "is",
  "it",
  "it-CH",
  "it-IT",
  "ja",
  "jw",
  "ka",
  "kk",
  "km",
  "kn",
  "ko",
  "ku",
  "ky",
  "la",
  "ln",
  "lo",
  "lt",
  "lv",
  "mk",
  "ml",
  "mn",
  "mo",
  "mr",
  "ms",
  "mt",
  "nb",
  "ne",
  "nl",
  "nn",
  "no",
  "oc",
  "om",
  "or",
  "pa",
  "pl",
  "ps",
  "pt",
  "pt-BR",
  "pt-PT",
  "qu",
  "rm",
  "ro",
  "ru",
  "sd",
  "sh",
  "si",
  "sk",
  "sl",
  "sn",
  "so",
  "sq",
  "sr",
  "st",
  "su",
  "sv",
  "sw",
  "ta",
  "te",
  "tg",
  "th",
  "ti",
  "tk",
  "to",
  "tr",
  "tt",
  "tw",
  "ug",
  "uk",
  "ur",
  "uz",
  "vi",
  "xh",
  "yi",
  "yo",
  "zh",
  "zh-CN",
  "zh-TW",
  "zu",
  ]

# initial_timezone: http://git.chromium.org/gitweb/?p=chromium.git;a=blob;f=chrome/browser/chromeos/system/timezone_settings.cc
INITIAL_TIMEZONE = [
  "Pacific/Majuro",
  "Pacific/Midway",
  "Pacific/Honolulu",
  "America/Anchorage",
  "America/Los_Angeles",
  "America/Tijuana",
  "America/Denver",
  "America/Phoenix",
  "America/Chihuahua",
  "America/Chicago",
  "America/Mexico_City",
  "America/Costa_Rica",
  "America/Regina",
  "America/New_York",
  "America/Bogota",
  "America/Caracas",
  "America/Barbados",
  "America/Manaus",
  "America/Santiago",
  "America/St_Johns",
  "America/Sao_Paulo",
  "America/Araguaina",
  "America/Argentina/Buenos_Aires",
  "America/Godthab",
  "America/Montevideo",
  "Atlantic/South_Georgia",
  "Atlantic/Azores",
  "Atlantic/Cape_Verde",
  "Africa/Casablanca",
  "Europe/London",
  "Europe/Amsterdam",
  "Europe/Belgrade",
  "Europe/Brussels",
  "Europe/Sarajevo",
  "Africa/Windhoek",
  "Africa/Brazzaville",
  "Asia/Amman",
  "Europe/Athens",
  "Asia/Beirut",
  "Africa/Cairo",
  "Europe/Helsinki",
  "Asia/Jerusalem",
  "Europe/Minsk",
  "Africa/Harare",
  "Asia/Baghdad",
  "Europe/Moscow",
  "Asia/Kuwait",
  "Africa/Nairobi",
  "Asia/Tehran",
  "Asia/Baku",
  "Asia/Tbilisi",
  "Asia/Yerevan",
  "Asia/Dubai",
  "Asia/Kabul",
  "Asia/Karachi",
  "Asia/Oral",
  "Asia/Yekaterinburg",
  "Asia/Calcutta",
  "Asia/Colombo",
  "Asia/Katmandu",
  "Asia/Almaty",
  "Asia/Rangoon",
  "Asia/Krasnoyarsk",
  "Asia/Bangkok",
  "Asia/Shanghai",
  "Asia/Hong_Kong",
  "Asia/Irkutsk",
  "Asia/Kuala_Lumpur",
  "Australia/Perth",
  "Asia/Taipei",
  "Asia/Seoul",
  "Asia/Tokyo",
  "Asia/Yakutsk",
  "Australia/Adelaide",
  "Australia/Darwin",
  "Australia/Brisbane",
  "Australia/Hobart",
  "Australia/Sydney",
  "Asia/Vladivostok",
  "Pacific/Guam",
  "Asia/Magadan",
  "Pacific/Auckland",
  "Pacific/Fiji",
  "Pacific/Tongatapu",
  ]

KNOWN_VPD_FIELD_DATA = {
  'keyboard_layout': KEYBOARD_LAYOUT,
  'initial_locale': INITIAL_LOCALE,
  'initial_timezone': INITIAL_TIMEZONE,
  }
