# -*- coding: utf-8 -*-
# Generated by Django 1.10.1 on 2017-04-11 09:43
from __future__ import unicode_literals

import backend.models
from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
      ('backend', '0006_auto_20161007_1518'),
  ]

  operations = [
      migrations.AlterField(
          model_name='temporaryuploadedfile',
          name='file',
          field=models.FileField(upload_to=backend.models.GenerateUploadToPath),
      ),
  ]
