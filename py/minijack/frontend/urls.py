# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from django.conf.urls import patterns, url
from django.conf.urls.static import static
from django.views.generic import RedirectView

import factory_common  # pylint: disable=W0611
from cros.factory.minijack.frontend import settings, views, query_views


urlpatterns = patterns(
  '',
  url(r'^device/(?P<device_id>[^/]*)$', views.GetDeviceView, name='device'),
  url(r'^event/(?P<event_id>[^/]*)$', views.GetEventView, name='event'),
  url(r'^query$', query_views.GetQueryView, name='query'),
  url(r'^devices$', views.GetDevicesView, name='devices'),
  url(r'^hwids$', views.GetHwidsView, name='hwids'),
  url(r'^screenshot/(?P<ip_address>[^/]*)$',
      views.GetScreenshotImage, name='screenshot'),
  url(r'^tests$', views.GetTestsView, name='tests'),
  url(r'^test$', views.GetTestView, name='test'),
  # RedirectView.as_view uses @classonlymethod, a subclass of @classmethod.
  # Pylint doesn't know the @classonlymethod and complains.
  url(r'^index$', RedirectView.as_view(url='/devices')), # pylint: disable=E1120
  url(r'^build$', RedirectView.as_view(url='/devices')), # pylint: disable=E1120
) + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
